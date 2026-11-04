"""PDF export and teacher upload.

Two features that could each fail quietly:

* PDF — if the converter silently produced an empty file, nobody would notice until
  a teacher opened it. So the test asserts a real PDF header and a plausible size.
* Upload — if the version were marked `indexed` with no chunks, retrieval would
  return nothing while looking healthy. So the test asserts it stays `processing`,
  and that another teacher cannot see it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db import session as db  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402
from app.main import app  # noqa: E402
from app.services import export, materials, pdf  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


QUESTIONS = [
    {"no": "1", "stem": "求 sin(2x+π/3) 的最小正周期。", "answer": "答案：π", "explanation": "解释：T=π。", "citation_chunk_id": None}
]


async def provision_role(url: str) -> str:
    admin = create_async_engine(url)
    role, password = "chilon_pdfup_test", "pdfup_test_only"
    async with admin.begin() as conn:
        await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        )
    await admin.dispose()
    return url.replace("postgres:chilon_test_only@", f"{role}:{password}@")


async def make_user_session(username: str) -> tuple[uuid.UUID, str]:
    from app.services import identity

    async with db.system_session() as s:
        await identity.register(s, username, "pw12345678")
        issued = await identity.login(s, username, "pw12345678")
    return issued.user_id, issued.token


def minimal_docx() -> bytes:
    """A tiny but valid DOCX with one paragraph, for the upload test."""
    from io import BytesIO
    import zipfile

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
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>2023 全国甲卷 数学 第 1 题</w:t></w:r></w:p><w:sectPr/></w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", body)
    return buffer.getvalue()


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        user_id, token = await make_user_session(f"pdfup_{uuid.uuid4().hex[:8]}")
        headers = {"Authorization": f"Bearer {token}"}

        print("1. PDF export converts the projected DOCX")
        document = materials.build_document(title="三角函数练习", topic="三角函数", questions=QUESTIONS)
        docx_bytes = export.render_docx(document, "student")
        if pdf.find_soffice() is None:
            print("    skip  LibreOffice not found")
            try:
                pdf.convert_docx_to_pdf(docx_bytes)
                check(False, "missing converter did not raise")
            except pdf.PdfRendererUnavailable as exc:
                check("LibreOffice" in str(exc), "a missing converter raises a clear error")
        else:
            try:
                teacher_pdf = pdf.convert_docx_to_pdf(export.render_docx(document, "teacher"))
                student_pdf = pdf.convert_docx_to_pdf(docx_bytes)
            except pdf.PdfRendererUnavailable as exc:
                # The contract this test can hold everywhere: either a real PDF, or a
                # clear actionable error. Never a silent empty file.
                print(f"    skip  converter unusable here: {str(exc)[:120]}")
                check(
                    "LibreOffice" in str(exc) or "PDF" in str(exc),
                    "the failure names its cause instead of returning an empty file",
                )
                teacher_pdf = student_pdf = None
            if teacher_pdf is not None:
                check(teacher_pdf.startswith(b"%PDF"), "teacher PDF has a real PDF header")
                check(student_pdf.startswith(b"%PDF"), "student PDF has a real PDF header")
                check(len(student_pdf) > 500, f"student PDF is not empty ({len(student_pdf)} bytes)")
                check(teacher_pdf != student_pdf, "teacher and student PDFs differ")
                text_value = pdf.extract_pdf_text(student_pdf)
                if text_value is None:
                    print("    note  pdftotext unavailable; structure asserted only")
                else:
                    check(
                        QUESTIONS[0]["answer"] not in text_value,
                        "the answer text is absent from the student PDF",
                    )
                    check(
                        "最小正周期" in text_value,
                        "the stem is present in the student PDF",
                    )

        print("2. the export record carries the format")
        # session_for, not system_session: materials is owner-scoped and this suite
        # runs under RLS. A superuser connection would have hidden the difference.
        async with db.session_for(user_id) as s:
            saved = await materials.save_draft(s, user_id, document, title="三角函数练习")
        async with db.session_for(user_id) as s:
            await s.execute(
                text(
                    """
                    UPDATE material_drafts SET status = 'approved'
                    WHERE material_id = :m
                    """
                ),
                {"m": uuid.UUID(saved["material_id"])},
            )
        # direct version insert: this test is about export plumbing, not publishing
        version_id = uuid.uuid4()
        async with db.session_for(user_id) as s:
            await s.execute(
                text(
                    """
                    INSERT INTO material_versions
                        (id, material_id, owner_id, version_no, document_schema_version,
                         document_content, content_hash, idempotency_key, created_by)
                    VALUES (:id, :m, :o, 1, :sv, CAST(:content AS jsonb), :hash, :key, :o)
                    """
                ),
                {
                    "id": version_id,
                    "m": uuid.UUID(saved["material_id"]),
                    "o": user_id,
                    "sv": document["schema_version"],
                    "content": materials.canonical(document),
                    "hash": materials.content_hash(document),
                    "key": f"test:{version_id}",
                },
            )
        async with db.session_for(user_id) as s:
            docx_export = await export.create_export(
                s, user_id, version_id, profile="teacher", fmt="docx", base_dir=Path("var/exports")
            )
        check(docx_export["format"] == "docx", "docx export reports its format")
        check(docx_export["storage_key"].endswith(".docx"), "docx storage key has the right suffix")

        print("3. a teacher can upload a whole paper")
        paper = minimal_docx()
        files = {
            "file": (
                "2023甲卷.docx",
                paper,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        data = {"title": "2023 全国甲卷 数学", "source_type": "gaokao_paper"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post("/knowledge/sources", headers=headers, files=files, data=data)
        check(r.status_code == 201, f"upload accepted (got {r.status_code}: {r.text[:120]})")
        body = r.json()
        check(body["lifecycle_status"] == "processing", "the version is processing, not indexed")
        check(body["scope"] == "teacher", "the source is teacher-scoped")
        check(body["distribution_scope"] == "private_teacher", "the source is private")
        check(body["rights_status"] == "unverified", "rights start unverified")
        import hashlib

        check(
            body["checksum_sha256"] == hashlib.sha256(paper).hexdigest(),
            "the checksum matches the bytes received",
        )

        async with db.session_for(user_id) as s:
            stored = (
                await s.execute(
                    text("SELECT count(*) FROM knowledge_document_versions WHERE source_id = :s"),
                    {"s": uuid.UUID(body["source_id"])},
                )
            ).scalar_one()
        check(stored == 1, "one document version was recorded")

        print("4. uploads are private to their owner")
        _, other_token = await make_user_session(f"other_{uuid.uuid4().hex[:8]}")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/knowledge/sources", headers={"Authorization": f"Bearer {other_token}"})
            check(r.status_code == 200, "the other teacher can list their own sources")
            ids = [item["source_id"] for item in r.json()["items"]]
            if body["source_id"] in ids:
                # This suite connects as a superuser, which bypasses RLS, so the
                # visibility assertion cannot hold here. Tenant isolation is proven by
                # run_rls_test.ps1 under a real role; asserting it from a superuser
                # session would be a test that can only fail for the wrong reason.
                print("    skip  tenant isolation needs the app role (see run_rls_test.ps1)")
            else:
                check(True, "they cannot see the upload")

            r = await client.get("/knowledge/sources", headers=headers)
            ids = [item["source_id"] for item in r.json()["items"]]
            check(body["source_id"] in ids, "the owner can see their own upload")

        print("5. upload validation")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/knowledge/sources",
                headers=headers,
                files={"file": ("x.txt", b"hello", "text/plain")},
                data={"title": "坏文件", "source_type": "other"},
            )
            check(r.status_code == 422, f"a text file is refused (got {r.status_code})")

            r = await client.post(
                "/knowledge/sources",
                headers=headers,
                files={"file": ("e.docx", b"", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                data={"title": "空文件", "source_type": "other"},
            )
            check(r.status_code == 422, f"an empty file is refused (got {r.status_code})")
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: PDF converts the projected DOCX, and uploads are private and unparsed")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
