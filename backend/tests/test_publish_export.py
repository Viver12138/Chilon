"""Publish and export: the file that reaches a student must not contain answers.

This is the last link, so it is tested the way a leak would actually be found: the
produced DOCX is unzipped and its text searched for the answer strings. A check that
only inspected the renderer's input would pass even if the renderer ignored the
projection.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402
from app.services import export, materials, publication  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


QUESTIONS = [
    {"no": "1", "stem": "求 f(x)=sin(2x+π/3) 的最小正周期。", "answer": "答案：π", "explanation": "解释：T=2π/2=π。", "citation_chunk_id": "c-1"},
    {"no": "2", "stem": "化简 sin²x+cos²x。", "answer": "答案：1", "explanation": "解释：同角基本关系。", "citation_chunk_id": None},
]


async def make_material(session, user_id: uuid.UUID) -> dict:
    doc = materials.build_document(title="三角函数练习", topic="三角函数", questions=QUESTIONS)
    saved = await materials.save_draft(session, user_id, doc, title="三角函数练习")
    return {"document": doc, **saved}


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    tmp_root = Path("var/exports")
    try:
        user_id = uuid.uuid4()
        async with db.session_for(user_id) as s:
            await s.execute(
                text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
                {"id": user_id, "u": f"pub_{user_id.hex[:10]}"},
            )
            material = await make_material(s, user_id)

        print("1. publishing is refused without a non-blocking quality report")
        async with db.session_for(user_id) as s:
            try:
                await publication.request_publication(
                    s, user_id, uuid.UUID(material["material_id"]), quality_verdict="blocked"
                )
                check(False, "a blocked quality report was allowed to publish")
            except publication.QualityBlocked:
                check(True, "blocked quality report stops publishing")

        async with db.session_for(user_id) as s:
            approval_id = await publication.request_publication(
                s,
                user_id,
                uuid.UUID(material["material_id"]),
                quality_verdict="passed_with_warnings",
                quality_summary={"blocking": 0, "issues": 3},
            )
        check(True, "a passing report yields a pending approval")

        print("2. an unapproved approval cannot publish")
        async with db.session_for(user_id) as s:
            try:
                await publication.publish(s, user_id, approval_id)
                check(False, "publishing without approval succeeded")
            except publication.ApprovalRequired:
                check(True, "publishing requires an approved approval")

        async with db.session_for(user_id) as s:
            await publication.approve_publication(s, approval_id, user_id)

        print("3. publish creates an immutable, numbered version")
        async with db.session_for(user_id) as s:
            version = await publication.publish(s, user_id, approval_id, change_summary="首次发布")
        check(version["version_no"] == 1, f"first version is 1 (got {version['version_no']})")
        check(len(version["content_hash"]) == 64, "version carries a content hash")

        async with db.session_for(user_id) as s:
            stored = (
                await s.execute(
                    text(
                        """
                        SELECT document_content, publication_approval_id
                        FROM material_versions WHERE id = :id
                        """
                    ),
                    {"id": uuid.UUID(version["version_id"])},
                )
            ).one()
        check(
            str(stored.publication_approval_id) == str(approval_id),
            "the version records which approval authorised it",
        )

        print("4. the same approval cannot publish twice")
        async with db.session_for(user_id) as s:
            try:
                await publication.publish(s, user_id, approval_id)
                check(False, "the approval was consumed twice")
            except publication.ApprovalRequired as exc:
                check("already" in str(exc).lower() or "consumed" in str(exc).lower(),
                      f"second publish refused ({exc})")

        print("5. export produces a real DOCX for both audiences")
        async with db.session_for(user_id) as s:
            teacher = await export.create_export(
                s, user_id, uuid.UUID(version["version_id"]), profile="teacher", base_dir=tmp_root
            )
            student = await export.create_export(
                s, user_id, uuid.UUID(version["version_id"]), profile="student", base_dir=tmp_root
            )
        check(teacher["status"] == "ready" and student["status"] == "ready", "both exports are ready")
        check(
            (tmp_root / Path(teacher["storage_key"]).name).exists(),
            "the teacher file exists on disk",
        )

        teacher_text = export.docx_text(teacher["bytes"])
        student_text = export.docx_text(student["bytes"])

        for q in QUESTIONS:
            if q["answer"] in teacher_text:
                check(True, f"Q{q['no']} answer present in the teacher file")
            else:
                check(False, f"Q{q['no']} answer missing from the teacher file")
            if q["answer"] not in student_text:
                check(True, f"Q{q['no']} answer absent from the student file")
            else:
                check(False, f"Q{q['no']} answer LEAKED into the student file")
            if q["explanation"] not in student_text:
                check(True, f"Q{q['no']} explanation absent from the student file")
            else:
                check(False, f"Q{q['no']} explanation LEAKED into the student file")

        for q in QUESTIONS:
            if q["stem"] in student_text:
                check(True, f"Q{q['no']} stem still present for the student")
            else:
                check(False, f"Q{q['no']} stem missing from the student file")

        print("6. exports are recorded with hashes and point at the version")
        async with db.session_for(user_id) as s:
            rows = (
                await s.execute(
                    text(
                        """
                        SELECT profile, status, file_hash, source_document_hash, material_version_id
                        FROM material_exports WHERE material_version_id = :v
                        ORDER BY profile
                        """
                    ),
                    {"v": uuid.UUID(version["version_id"])},
                )
            ).all()
        check(len(rows) == 2, f"two export records (got {len(rows)})")
        check(all(r.status == "ready" for r in rows), "both records are ready")
        check(all(len(r.file_hash) == 64 for r in rows), "each export has a file hash")
        check(
            all(r.source_document_hash == version["content_hash"] for r in rows),
            "both exports trace to the same source document hash",
        )
        check(
            len({r.file_hash for r in rows}) == 2,
            "teacher and student files differ (they are not the same bytes)",
        )
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: publish is single-use and the student file physically lacks the answers")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
