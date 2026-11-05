"""Closing the review loop: add the missing question, then promote the version.

Parsing produces `pending_review` when the numbering has holes. Until now the teacher
could **see** the hole but not fix it, which makes the state a dead end — and a dead end
is worse than no state at all, because it looks like a workflow.

Two operations, both owner-scoped by RLS:

* `add_question` — writes a **chunk and a question together**. A question without a
  chunk is invisible to retrieval, so "I added it but it doesn't show up" would be the
  obvious next bug.
* `promote` — moves the version to `indexed` so retrieval picks it up. It records what
  gaps were still open at that moment: the teacher may know that a paper genuinely skips
  a number, and the record should say the decision was made rather than that nothing was
  missing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ingestion, taxonomy


class ReviewError(Exception):
    pass


class ReviewNotFound(ReviewError):
    """The version does not exist, or the caller cannot see it."""

    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manual_locator(number: int, *, answer: bool = False) -> dict[str, Any]:
    key = "answer_index" if answer else "question_index"
    return {"manual": True, key: number}


async def outline(session: AsyncSession, owner_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, Any]:
    """What this version has, and what it is missing."""
    version = (
        await session.execute(
            text(
                """
                SELECT id, source_id, lifecycle_status, version_no
                FROM knowledge_document_versions WHERE id = :v
                """
            ),
            {"v": version_id},
        )
    ).first()
    if version is None:
        raise ReviewNotFound("document version not found")

    rows = (
        await session.execute(
            text(
                """
                SELECT question_no, current_paper_question_type, current_knowledge_points,
                       answer_locator IS NOT NULL AS has_answer
                FROM knowledge_questions WHERE document_version_id = :v
                  AND deleted_at IS NULL
                ORDER BY ordinal
                """
            ),
            {"v": version_id},
        )
    ).all()

    numbers: list[int] = []
    for row in rows:
        try:
            numbers.append(int(str(row.question_no).strip()))
        except (TypeError, ValueError):
            continue
    numbers.sort()
    gaps = [n for n in range(1, numbers[-1] + 1) if n not in numbers] if numbers else []

    return {
        "document_version_id": str(version_id),
        "source_id": str(version.source_id),
        "lifecycle_status": version.lifecycle_status,
        "version_no": version.version_no,
        "questions": len(rows),
        "numbers": numbers,
        "gaps": gaps,
    }


async def add_question(
    session: AsyncSession,
    owner_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    number: int,
    stem: str,
    answer: str | None = None,
) -> dict[str, Any]:
    """Add one manually transcribed question, as a chunk **and** a question."""
    # Visibility first: RLS would reject the insert, but "this is not yours" must read as
    # a clean 404 rather than a database exception surfacing as a server error.
    await outline(session, owner_id, version_id)

    stem = (stem or "").strip()
    if not stem:
        raise ReviewError("题干不能为空")
    if number < 1 or number > 200:
        raise ReviewError("题号必须在 1..200 之间")

    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM knowledge_questions WHERE document_version_id = :v AND question_no = :n"
            ),
            {"v": version_id, "no": number, "n": str(number)},
        )
    ).first()
    if existing:
        raise ReviewError(f"第 {number} 题已存在")

    locator = _manual_locator(number)
    ordinal = 100000 + number  # manual entries sort after parsed ones, stable
    await session.execute(
        text(
            """
            INSERT INTO knowledge_chunks
                (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                 locator, content_kind, parser_version, parse_schema_version)
            VALUES
                (gen_random_uuid(), :v, :key, :ordinal, :body, :hash,
                 CAST(:locator AS jsonb), 'text', 'manual', '1.0')
            """
        ),
        {
            "v": version_id,
            "key": f"m{number:05d}",
            "ordinal": ordinal,
            "body": stem,
            "hash": _hash(stem),
            "locator": json.dumps(locator, sort_keys=True),
        },
    )

    answer_locator_json: str | None = None
    answer_text = (answer or "").strip()
    if answer_text:
        answer_locator = _manual_locator(number, answer=True)
        answer_locator_json = json.dumps(answer_locator, sort_keys=True)
        await session.execute(
            text(
                """
                INSERT INTO knowledge_chunks
                    (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                     locator, content_kind, parser_version, parse_schema_version)
                VALUES
                    (gen_random_uuid(), :v, :key, :ordinal, :body, :hash,
                     CAST(:locator AS jsonb), 'text', 'manual', '1.0')
                """
            ),
            {
                "v": version_id,
                "key": f"ma{number:05d}",
                "ordinal": ordinal + 10000,
                "body": answer_text,
                "hash": _hash(answer_text),
                "locator": answer_locator_json,
            },
        )

    await session.execute(
        text(
            """
            INSERT INTO knowledge_questions
                (id, document_version_id, question_no, section_label, ordinal, stem_locator,
                 answer_locator, current_paper_question_type, current_knowledge_points,
                 segmentation_status, segmentation_source)
            VALUES
                (gen_random_uuid(), :v, :no, NULL, :ordinal, CAST(:locator AS jsonb),
                 CAST(:answer_locator AS jsonb), :qtype, CAST(:points AS text[]),
                 'accepted', 'teacher')
            """
        ),
        {
            "v": version_id,
            "no": str(number),
            "ordinal": ordinal,
            "locator": json.dumps(locator, sort_keys=True),
            "answer_locator": answer_locator_json,
            "qtype": ingestion.classify(None, stem),
            "points": taxonomy.tag(stem) or None,
        },
    )

    return {
        "document_version_id": str(version_id),
        "question_no": str(number),
        "questions": 1,
        "segmentation_source": "teacher",
    }


async def promote(
    session: AsyncSession, owner_id: uuid.UUID, version_id: uuid.UUID
) -> dict[str, Any]:
    """Make the version retrievable, recording the gaps that were still open."""
    state = await outline(session, owner_id, version_id)
    if state["lifecycle_status"] == "indexed":
        return {**state, "promoted": False, "reason": "already indexed"}
    if state["lifecycle_status"] == "failed":
        raise ReviewError("这个版本解析失败，不能直接启用；请重新上传")
    if state["questions"] == 0:
        raise ReviewError("没有题目，不能启用")

    await session.execute(
        text(
            """
            UPDATE knowledge_document_versions
            SET lifecycle_status = 'indexed', indexed_at = now()
            WHERE id = :v
            """
        ),
        {"v": version_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO knowledge_ingestion_runs
                (id, document_version_id, stage, status, tool_version,
                 started_at, finished_at, metrics)
            VALUES
                (gen_random_uuid(), :v, 'index', 'succeeded', 'manual-review',
                 now(), now(), CAST(:metrics AS jsonb))
            """
        ),
        {
            "v": version_id,
            "metrics": json.dumps(
                {
                    "promoted_by": "teacher",
                    "questions": state["questions"],
                    # the decision to publish despite these holes is the teacher's, so
                    # the holes are recorded with the decision
                    "open_gaps_at_promotion": state["gaps"],
                },
                ensure_ascii=False,
            ),
        },
    )
    return {
        "document_version_id": str(version_id),
        "promoted": True,
        "questions": state["questions"],
        "open_gaps_at_promotion": state["gaps"],
    }

async def _chunk_ids(
    session: AsyncSession, version_id: uuid.UUID, number: int
) -> tuple[uuid.UUID | None, uuid.UUID | None, dict | None, dict | None]:
    """Locate the stem chunk and the answer chunk of one question."""
    row = (
        await session.execute(
            text(
                """
                SELECT stem_locator, answer_locator FROM knowledge_questions
                WHERE document_version_id = :v AND question_no = :n
                """
            ),
            {"v": version_id, "n": str(number)},
        )
    ).first()
    if row is None:
        raise ReviewNotFound(f"第 {number} 题不存在")

    async def one(locator):
        if not locator:
            return None
        return (
            await session.execute(
                text(
                    "SELECT id FROM knowledge_chunks WHERE document_version_id = :v "
                    "AND locator = CAST(:l AS jsonb)"
                ),
                {"v": version_id, "l": json.dumps(locator, sort_keys=True)},
            )
        ).scalar()

    return (
        await one(row.stem_locator),
        await one(row.answer_locator),
        row.stem_locator,
        row.answer_locator,
    )


async def update_question(
    session: AsyncSession,
    owner_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    number: int,
    stem: str | None = None,
    answer: str | None = None,
) -> dict[str, Any]:
    """Correct a question that was cut or recognised wrongly.

    The **chunk** is updated, not just the question row: retrieval reads chunks, so a
    correction that only touched `knowledge_questions` would leave search returning the
    old text while the page showed the new one.
    """
    await outline(session, owner_id, version_id)
    stem_chunk, answer_chunk, stem_locator, answer_locator = await _chunk_ids(
        session, version_id, number
    )

    new_stem = (stem or "").strip()
    if new_stem:
        if stem_chunk is None:
            raise ReviewError("这一题没有对应的文本块，无法修改")
        await session.execute(
            text(
                "UPDATE knowledge_chunks SET text_content = :body, text_hash = :hash WHERE id = :id"
            ),
            {"body": new_stem, "hash": _hash(new_stem), "id": stem_chunk},
        )
        await session.execute(
            text(
                """
                UPDATE knowledge_questions
                SET current_paper_question_type = :qtype,
                    current_knowledge_points = CAST(:points AS text[]),
                    segmentation_status = 'corrected', segmentation_source = 'teacher',
                    updated_at = now()
                WHERE document_version_id = :v AND question_no = :n
                """
            ),
            {
                "qtype": ingestion.classify(None, new_stem),
                "points": taxonomy.tag(new_stem) or None,
                "v": version_id,
                "n": str(number),
            },
        )

    answer_text = (answer or "").strip()
    if answer_text:
        if answer_chunk is not None:
            await session.execute(
                text(
                    "UPDATE knowledge_chunks SET text_content = :body, text_hash = :hash WHERE id = :id"
                ),
                {"body": answer_text, "hash": _hash(answer_text), "id": answer_chunk},
            )
        else:
            locator = _manual_locator(number, answer=True)
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunks
                        (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                         locator, content_kind, parser_version, parse_schema_version)
                    VALUES (gen_random_uuid(), :v, :key, :ordinal, :body, :hash,
                            CAST(:locator AS jsonb), 'text', 'manual', '1.0')
                    """
                ),
                {
                    "v": version_id,
                    "key": f"ma{number:05d}",
                    "ordinal": 100000 + number + 10000,
                    "body": answer_text,
                    "hash": _hash(answer_text),
                    "locator": json.dumps(locator, sort_keys=True),
                },
            )
            await session.execute(
                text(
                    "UPDATE knowledge_questions SET answer_locator = CAST(:l AS jsonb), "
                    "updated_at = now() WHERE document_version_id = :v AND question_no = :n"
                ),
                {
                    "l": json.dumps(locator, sort_keys=True),
                    "v": version_id,
                    "n": str(number),
                },
            )

    return {"document_version_id": str(version_id), "question_no": str(number), "updated": True}


async def delete_question(
    session: AsyncSession, owner_id: uuid.UUID, version_id: uuid.UUID, *, number: int
) -> dict[str, Any]:
    """Remove a question from everything the teacher sees, reversibly.

    The row is kept and stamped `deleted_at`; only the chunks go. Deleting the row would
    make the action final, and a mis-click would cost a re-typed question — so the
    reversible version is the one implemented, and the chunks still go because
    retrieval must stop returning it immediately.
    """
    await outline(session, owner_id, version_id)
    stem_chunk, answer_chunk, _, _ = await _chunk_ids(session, version_id, number)

    await session.execute(
        text(
            "UPDATE knowledge_questions SET deleted_at = now(), updated_at = now() "
            "WHERE document_version_id = :v AND question_no = :n AND deleted_at IS NULL"
        ),
        {"v": version_id, "n": str(number)},
    )
    for chunk_id in (stem_chunk, answer_chunk):
        if chunk_id is not None:
            await session.execute(
                text("DELETE FROM knowledge_chunks WHERE id = :id"), {"id": chunk_id}
            )
    return {"document_version_id": str(version_id), "question_no": str(number), "deleted": True}


async def restore_question(
    session: AsyncSession, owner_id: uuid.UUID, version_id: uuid.UUID, *, number: int
) -> dict[str, Any]:
    """Undo a delete by re-creating the question from what was kept."""
    await outline(session, owner_id, version_id)
    row = (
        await session.execute(
            text(
                """
                SELECT id FROM knowledge_questions
                WHERE document_version_id = :v AND question_no = :n AND deleted_at IS NOT NULL
                """
            ),
            {"v": version_id, "n": str(number)},
        )
    ).first()
    if row is None:
        raise ReviewNotFound(f"第 {number} 题没有待恢复的删除记录")

    await session.execute(
        text("UPDATE knowledge_questions SET deleted_at = NULL, updated_at = now() WHERE id = :id"),
        {"id": row.id},
    )
    return {"document_version_id": str(version_id), "question_no": str(number), "restored": True}


async def renumber(
    session: AsyncSession,
    owner_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    number: int,
    new_number: int,
) -> dict[str, Any]:
    """Move a question to another number.

    Needed when the cutter merged two questions into one block: the fix is to add the
    second one and shift the rest, not to delete and retype everything after it.
    """
    await outline(session, owner_id, version_id)
    if number == new_number:
        return {"document_version_id": str(version_id), "moved": False}
    taken = (
        await session.execute(
            text(
                "SELECT 1 FROM knowledge_questions WHERE document_version_id = :v "
                "AND question_no = :n AND deleted_at IS NULL"
            ),
            {"v": version_id, "n": str(new_number)},
        )
    ).first()
    if taken:
        raise ReviewError(f"第 {new_number} 题已存在，不能占用")

    result = await session.execute(
        text(
            "UPDATE knowledge_questions SET question_no = :new, updated_at = now() "
            "WHERE document_version_id = :v AND question_no = :old AND deleted_at IS NULL"
        ),
        {"v": version_id, "new": str(new_number), "old": str(number)},
    )
    if result.rowcount == 0:
        raise ReviewNotFound(f"第 {number} 题不存在")
    return {"document_version_id": str(version_id), "from": number, "to": new_number, "moved": True}
