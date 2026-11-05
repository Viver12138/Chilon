"""Ingestion tests: an uploaded paper becomes retrievable content.

The property under test is the one that was missing: **a teacher's own paper is
findable**. Before this, an upload was stored and never parsed, so retrieval returned
zero while the version looked healthy in every listing.

Written as the teacher's path: upload over HTTP, then retrieve with the same tool the
agent uses.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import identity, ingestion  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PARAGRAPHS = [
    "2023 年全国甲卷 数学",
    "一、选择题",
    "1. 已知三角函数 f(x)=sin(2x+π/3)，求其最小正周期与单调递增区间。",
    "A. π  B. 2π  C. π/2  D. 4π",
    "2. 化简 sin²x + cos²x + tan x·cot x。",
    "3. 在 △ABC 中，a=3，b=4，C=90°，求 c。",
]


def make_docx(paragraphs: list[str]) -> bytes:
    def escaped(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = "".join(
        f"<w:p><w:r><w:t xml:space='preserve'>{escaped(p)}</w:t></w:r></w:p>" for p in paragraphs
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def search_ctx(owner_id, requirement):
    return tools_impl.ToolContext(
        owner_id=owner_id,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement=requirement,
        deps={},
    )


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        async with db.system_session() as session:
            username = f"ing_{uuid.uuid4().hex[:8]}"
            owner = await identity.register(session, username, "ingest_password_1")
            issued = await identity.login(session, username, "ingest_password_1")
        headers = {"Authorization": f"Bearer {issued.token}"}

        print("1. uploading parses immediately")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/knowledge/sources",
                headers=headers,
                files={"file": ("2023甲卷.docx", make_docx(PARAGRAPHS), DOCX_MIME)},
                data={"title": "2023 全国甲卷 数学", "source_type": "gaokao_paper"},
            )
        check(r.status_code == 201, f"upload accepted (got {r.status_code}: {r.text[:160]})")
        body = r.json()
        check(body["lifecycle_status"] == "indexed", f"version indexed (got {body['lifecycle_status']})")
        check(body["chunks"] == 4, f"4 chunks (got {body['chunks']})")
        check(body["questions"] == 3, f"3 questions (got {body['questions']})")
        source_id = uuid.UUID(body["source_id"])

        print("2. the chunks and questions are stored with matching locators")
        async with db.session_for(owner) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.text_content, q.stem_locator AS q_loc, c.locator AS c_loc
                        FROM knowledge_chunks c
                        LEFT JOIN knowledge_questions q
                               ON q.document_version_id = c.document_version_id
                              AND q.stem_locator = c.locator
                        WHERE c.document_version_id = :v
                        ORDER BY c.ordinal
                        """
                    ),
                    {"v": uuid.UUID(body["document_version_id"])},
                )
            ).all()
        check(len(rows) == 4, f"4 chunk rows (got {len(rows)})")
        linked = [r for r in rows if r.q_loc is not None]
        check(len(linked) == 3, f"3 chunks are linked to a question (got {len(linked)})")
        check(
            all(r.c_loc == r.q_loc for r in linked),
            "question locators equal their chunk locators",
        )

        print("3. retrieval finds the teacher's own paper")
        async with db.session_for(owner) as session:
            found = await tools_impl.knowledge_search(
                session,
                search_ctx(owner, {"topic": "三角函数", "sources": []}),
            )
        check(len(found["hits"]) >= 1, f"retrieval returned {len(found['hits'])} hit(s)")
        check(
            any("sin(2x+π/3)" in hit["excerpt"] for hit in found["hits"]),
            "the uploaded passage is among the hits",
        )
        check(
            any(hit.get("question_no") == "1" for hit in found["hits"]),
            "the hit is linked to question 1",
        )

        print("4. another teacher cannot see it")
        async with db.system_session() as session:
            other_name = f"ing_other_{uuid.uuid4().hex[:6]}"
            other = await identity.register(session, other_name, "other_password_1")
        async with db.session_for(other) as session:
            theirs = await tools_impl.knowledge_search(
                session, search_ctx(other, {"topic": "三角函数", "sources": []})
            )
        check(len(theirs["hits"]) == 0, f"the other teacher sees {len(theirs['hits'])} hit(s)")

        print("5. re-ingesting replaces rather than appends")
        async with db.session_for(owner) as session:
            again = await ingestion.ingest_latest(session, owner, source_id)
        check(again["chunks"] == 4, f"still 4 chunks after re-ingest (got {again['chunks']})")
        async with db.session_for(owner) as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM knowledge_chunks WHERE document_version_id = :v"),
                    {"v": uuid.UUID(body["document_version_id"])},
                )
            ).scalar_one()
        check(count == 4, f"no duplicated chunks (got {count})")

        print("6. a PDF is refused with a reason, and the version is marked failed")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/knowledge/sources",
                headers=headers,
                files={"file": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"title": "扫描件", "source_type": "other"},
            )
        check(r.status_code == 201, f"the file is still stored (got {r.status_code})")
        pdf_body = r.json()
        check(pdf_body["lifecycle_status"] == "failed", f"parse failed (got {pdf_body['lifecycle_status']})")
        check(pdf_body["parse_error"] == "unsupported_format", "the reason is unsupported_format")
        check("DOCX" in (pdf_body["parse_detail"] or ""), "the message names what to do instead")

        async with db.session_for(owner) as session:
            run = (
                await session.execute(
                    text(
                        """
                        SELECT status, error_code FROM knowledge_ingestion_runs
                        WHERE document_version_id = :v ORDER BY started_at DESC LIMIT 1
                        """
                    ),
                    {"v": uuid.UUID(pdf_body["document_version_id"])},
                )
            ).one()
        check(run.status == "failed" and run.error_code == "unsupported_format", "the run row records why")

    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: an uploaded paper is parsed, linked and retrievable by its owner only")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
