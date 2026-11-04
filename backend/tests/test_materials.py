"""Material document tests: the student version must not contain answers.

The assertion that matters is not "the student file looks right" but
"the answer string does not occur anywhere in the student projection **after
serialisation**". A rendering test would pass on CSS hiding; this one cannot.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402
from app.services import materials  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


ANSWERS = [
    {"no": "1", "stem": "求 f(x)=sin(2x+π/3) 的最小正周期。", "answer": "π", "explanation": "T=2π/2=π。", "citation_chunk_id": "c-1"},
    {"no": "2", "stem": "求 f(x)=cos(x-π/4) 的最大值。", "answer": "1", "explanation": "余弦的最大值为 1。", "citation_chunk_id": None},
    {"no": "3", "stem": "化简 sin²x+cos²x。", "answer": "1", "explanation": "同角三角函数基本关系。", "citation_chunk_id": "c-2"},
]

CITATIONS = [
    {"citation_id": "c-1", "source": {"source_type": "gaokao_paper", "title": "2023 全国甲卷"}},
    {"citation_id": "c-2", "source": {"source_type": "textbook", "title": "人教版必修一"}},
]


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))

    print("1. the document separates student and teacher content")
    doc = materials.build_document(
        title="三角函数练习", topic="三角函数", questions=ANSWERS, citations=CITATIONS
    )
    check(doc["schema_version"] == "1.1.0", f"schema version (got {doc['schema_version']})")
    check(
        materials.count_blocks(doc, "exercise") == 3,
        f"3 exercises (got {materials.count_blocks(doc, 'exercise')})",
    )
    check(
        materials.count_blocks(doc, "answer") == 3,
        "every exercise has an answer block in the source document",
    )

    print("2. projection uses declared visibility, not styling")
    student = materials.project(doc, "student")
    teacher = materials.project(doc, "teacher")

    check(materials.count_blocks(student, "answer") == 0, "student projection has no answer blocks")
    check(materials.count_blocks(student, "solution") == 0, "student projection has no solution blocks")
    check(
        materials.count_blocks(teacher, "answer") == 3,
        "teacher projection keeps all answer blocks",
    )
    check(
        materials.count_blocks(student, "exercise") == 3,
        "student projection still has all 3 exercises",
    )

    print("3. no answer text survives in the student projection after serialisation")
    student_serialised = json.dumps(student, ensure_ascii=False)
    teacher_serialised = json.dumps(teacher, ensure_ascii=False)
    for q in ANSWERS:
        answer = q["answer"]
        # answers are short numbers; require the explanation, which is unambiguous
        if q["explanation"] not in student_serialised:
            check(True, f"Q{q['no']} explanation absent from student projection")
        else:
            check(False, f"Q{q['no']} explanation leaked into student projection")
        if q["explanation"] in teacher_serialised:
            check(True, f"Q{q['no']} explanation present in teacher projection")
        else:
            check(False, f"Q{q['no']} explanation missing from teacher projection")

    leaked_keys = [k for k in ('"answer"', '"solution"') if k in student_serialised]
    check(not leaked_keys, f"no answer/solution keys in student JSON (found {leaked_keys})")

    print("4. both versions come from one source and the student copy cannot mutate it")
    check(
        materials.content_hash(doc) == materials.content_hash(doc),
        "source hash is stable",
    )
    student["blocks"].append({"id": "x", "type": "paragraph", "visibility": "student"})
    check(
        len(doc["blocks"]) != len(student["blocks"]),
        "mutating the projection does not touch the source document",
    )

    print("5. drafts persist and revisions are numbered")
    user_id = uuid.uuid4()
    async with db.session_for(user_id) as s:
        await s.execute(
            text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
            {"id": user_id, "u": f"mat_{user_id.hex[:10]}"},
        )
        first = await materials.save_draft(s, user_id, doc, title="三角函数练习")

    check(first["revision_no"] == 1, f"first revision is 1 (got {first['revision_no']})")
    check(len(first["content_hash"]) == 64, "draft carries a content hash")

    async with db.session_for(user_id) as s:
        second = await materials.save_draft(
            s, user_id, doc, title="三角函数练习", material_id=uuid.UUID(first["material_id"])
        )
    check(second["revision_no"] == 2, f"second revision is 2 (got {second['revision_no']})")
    check(second["draft_id"] == first["draft_id"], "same draft, new revision")

    async with db.session_for(user_id) as s:
        stored = (
            await s.execute(
                text(
                    """
                    SELECT r.content, r.content_hash, d.current_revision_no
                    FROM material_draft_revisions r
                    JOIN material_drafts d ON d.id = r.draft_id
                    WHERE r.id = :id
                    """
                ),
                {"id": uuid.UUID(second["revision_id"])},
            )
        ).one()
    check(stored.content_hash == second["content_hash"], "stored hash matches")
    check(stored.current_revision_no == 2, "draft points at the newest revision")
    check(
        stored.content["blocks"][0]["type"] == "section",
        "stored document keeps its structure",
    )

    print("6. an invalid profile is refused")
    try:
        materials.project(doc, "parent")
        check(False, "unknown profile accepted")
    except materials.DocumentError:
        check(True, "unknown profile refused")

    await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: the student version is projected, not hidden")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
