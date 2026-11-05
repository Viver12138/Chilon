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
