"""Platform corpus tests: import, then a teacher can use it but not touch it.

The three properties that make the shared corpus trustworthy:

1. a teacher can **retrieve** platform content without owning it;
2. a teacher **cannot write** into it — the child-table policies were narrowed for this;
3. re-importing the same file is a no-op, because the corpus gets imported repeatedly.

Runs the import on an admin session (as the tool does) and everything else on the
application role.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import identity, platform_import  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.support import admin_session, provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


PARAGRAPHS = [
    "2024 年全国甲卷 数学（理）",
    "一、选择题",
    "1. 已知集合 A={1,2,3}，B={2,3}，求 A∩B。",
    "2. 已知复数 z=1+i，求 |z|。",
    "3. 已知数列 {a_n} 为等差数列，a_1=1，公差 d=2，求 a_10。",
]


def make_docx(paragraphs: list[str]) -> bytes:
    def escaped(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = "".join(
        f"<w:p><w:r><w:t xml:space='preserve'>{escaped(p)}</w:t></w:r></w:p>" for p in paragraphs
    )
    types = (
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
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def search_ctx(owner_id, topic: str):
    return tools_impl.ToolContext(
        owner_id=owner_id,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement={"topic": topic, "sources": []},
        deps={},
    )


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    scratch = Path("var/platform_import_test.docx")
    try:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_bytes(make_docx(PARAGRAPHS))

        print("1. an operator imports a paper into the platform corpus")
        async with admin_session() as session:
            result = await platform_import.import_document(
                session,
                path=scratch,
                title="2024 全国甲卷 数学（理）",
                source_type="gaokao_paper",
            )
        check(not result["skipped"], "first import is not a skip")
        check(result["scope"] == "platform", f"scope is platform (got {result['scope']})")
        check(result["questions"] == 3, f"three questions (got {result['questions']})")
        check(result["status"] == "indexed", f"indexed (got {result['status']})")
        version_id = uuid.UUID(result["document_version_id"])

        async with admin_session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT s.scope, s.owner_id, s.rights_status, s.created_by,
                               v.lifecycle_status
                        FROM knowledge_sources s
                        JOIN knowledge_document_versions v ON v.source_id = s.id
                        WHERE v.id = :v
                        """
                    ),
                    {"v": version_id},
                )
            ).one()
        check(row.scope == "platform", "the source is platform-scoped")
        check(row.owner_id is None, "and has no owner")
        check(row.rights_status == "licensed", f"rights are licensed (got {row.rights_status})")
        check(
            row.created_by == platform_import.PLATFORM_PRINCIPAL,
            "created_by carries the documented system principal placeholder",
        )
        check(row.lifecycle_status == "indexed", "the version is retrievable")

        print("2. a teacher can retrieve it without owning it")
        async with db.system_session() as session:
            teacher_name = f"plat_{uuid.uuid4().hex[:8]}"
            teacher = await identity.register(session, teacher_name, "platform_password_1")
        async with db.session_for(teacher) as session:
            hits = await tools_impl.knowledge_search(session, search_ctx(teacher, "集合"))
        check(len(hits["hits"]) >= 1, f"retrieved {len(hits['hits'])} hit(s)")
        check(
            any("A∩B" in (h.get("excerpt") or "") for h in hits["hits"]),
            "the platform question is among them",
        )

        print("3. a teacher cannot write into platform content")
        denied = False
        try:
            async with db.session_for(teacher) as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_chunks
                            (id, document_version_id, chunk_key, ordinal, text_content,
                             text_hash, locator, content_kind, parser_version,
                             parse_schema_version)
                        VALUES (gen_random_uuid(), :v, 'evil', 1, '注入的内容', :h,
                                '{"paragraph_start": 0}'::jsonb, 'text', 'x', '1.0')
                        """
                    ),
                    {"v": version_id, "h": hashlib.sha256(b"evil").hexdigest()},
                )
        except Exception as exc:  # noqa: BLE001 - the point is that it raises
            denied = "row-level security" in str(exc) or "InsufficientPrivilege" in type(exc).__name__
        check(denied, "the insert is refused by RLS")

        print("4. re-importing the same file is a no-op")
        async with admin_session() as session:
            again = await platform_import.import_document(
                session, path=scratch, title="重复导入", source_type="gaokao_paper"
            )
        check(again["skipped"], "the second import is skipped")
        check(
            again["document_version_id"] == result["document_version_id"],
            "and points at the same version",
        )

        async with admin_session() as session:
            count = (
                await session.execute(
                    text(
                        """
                        SELECT count(*) FROM knowledge_sources
                        WHERE scope = 'platform'
                          AND title IN ('2024 全国甲卷 数学（理）', '重复导入')
                        """
                    )
                )
            ).scalar_one()
        check(count == 1, f"only one platform source exists (got {count})")
    finally:
        scratch.unlink(missing_ok=True)
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: the platform corpus is importable, shared, and read-only to teachers")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
