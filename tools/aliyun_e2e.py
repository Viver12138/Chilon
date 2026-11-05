"""End-to-end run against the real Aliyun endpoint, on a real exam paper.

Separate from the test suite on purpose: it needs credentials **and** network, so it
must never be part of the offline suite that has to stay green everywhere. Run it by
hand when credentials exist:

    python tools/aliyun_e2e.py

It ingests `docs/2024年新课标全国Ⅰ卷数学真题（原卷版）.pdf` through the same code path an
upload takes, then reports what landed in the database.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app import settings as config  # noqa: E402
from app.db import session as db  # noqa: E402
from app.services import identity, ingestion  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

SAMPLE = Path(os.environ.get("CHILON_SAMPLE", str(ROOT / "docs/2024年新课标全国Ⅰ卷数学真题（原卷版）.pdf")))


def search_ctx(owner_id):
    return tools_impl.ToolContext(
        owner_id=owner_id,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement={"topic": "集合", "sources": []},
        deps={},
    )


async def main() -> int:
    settings = config.load()
    if not settings.ocr_aliyun_key_id:
        print("no aliyun credentials in .env", file=sys.stderr)
        return 2
    if not SAMPLE.exists():
        print(f"sample paper not found: {SAMPLE}", file=sys.stderr)
        return 2

    url = os.environ.get("CHILON_DATABASE_URL")
    if not url:
        print("CHILON_DATABASE_URL is not set", file=sys.stderr)
        return 2

    os.environ["CHILON_OCR_PROVIDER"] = "aliyun"
    db.init(await provision_runtime_role(url))
    try:
        async with db.system_session() as session:
            username = f"e2e_{uuid.uuid4().hex[:8]}"
            owner = await identity.register(session, username, "e2e_password_1")
        # owner-scoped tables need that owner's context
        async with db.session_for(owner) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_categories (id, scope, owner_id, key, name, is_system)
                    VALUES (gen_random_uuid(), 'teacher', :o, 'e2e', '联调', false)
                    """
                ),
                {"o": owner},
            )

        async with db.session_for(owner) as session:
            source_id = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_sources
                        (id, scope, owner_id, category_id, source_type, title,
                         rights_status, distribution_scope, created_by)
                    SELECT :id, 'teacher', :o, c.id, 'gaokao_paper', '2024 新课标Ⅰ卷',
                           'unverified', 'private_teacher', :o
                    FROM knowledge_categories c
                    WHERE c.scope = 'teacher' AND c.owner_id = :o LIMIT 1
                    """
                ),
                {"id": source_id, "o": owner},
            )

        suffix = SAMPLE.suffix.lower()
        mime = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }.get(suffix, "application/pdf")
        version_id = uuid.uuid4()
        storage_key = f"uploads/{source_id}/{version_id}{suffix}"
        data = SAMPLE.read_bytes()
        target = Path(ingestion.UPLOAD_ROOT) / storage_key.split("uploads/", 1)[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        async with db.session_for(owner) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_document_versions
                        (id, source_id, version_no, storage_key, checksum_sha256,
                         mime_type, file_size_bytes, lifecycle_status, uploaded_by)
                    VALUES (:id, :s, 1, :k, :h, :mime, :size, 'processing', :o)
                    """
                ),
                {
                    "id": version_id,
                    "s": source_id,
                    "k": storage_key,
                    "h": "d" * 64,
                    "mime": mime,
                    "size": len(data),
                    "o": owner,
                },
            )

        print(f"ingesting {SAMPLE.name} ({len(data)} bytes) with aliyun...")
        async with db.session_for(owner) as session:
            result = await ingestion.ingest(session, owner, version_id)

        import json as _json
        print("\nfull result:", _json.dumps(result, ensure_ascii=False, default=str))
        print(f"\nstatus      : {result['status']}")
        print(f"questions   : {result['questions']}")
        print(f"answers     : {result.get('answers', 0)}")
        print(f"chunks      : {result['chunks']}")
        print(f"needs_review: {result.get('needs_review')}")
        print(f"ocr         : {result.get('ocr')}")

        async with db.session_for(owner) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT question_no, current_paper_question_type, current_knowledge_points
                        FROM knowledge_questions WHERE document_version_id = :v
                        ORDER BY ordinal LIMIT 8
                        """
                    ),
                    {"v": version_id},
                )
            ).all()
        print("\nfirst questions:")
        for row in rows:
            print(
                f"  no={row.question_no} type={row.current_paper_question_type} "
                f"points={row.current_knowledge_points}"
            )

        async with db.session_for(owner) as session:
            search = await tools_impl.knowledge_search(session, search_ctx(owner))
        print(f"\nretrieval for '集合': {len(search['hits'])} hit(s)")
        for hit in search["hits"][:2]:
            print(f"  {hit['excerpt'][:70]}")

        return 0 if result["questions"] > 0 else 1
    finally:
        await db.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
