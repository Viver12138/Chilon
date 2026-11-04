"""Material documents, projection, and draft persistence.

The export contract that matters: **the student version is projected from the AST,
not hidden with styling.** Every block declares `visibility` (`student` or
`teacher`), and the student projection physically lacks the teacher blocks. Copying,
converting or re-formatting a student file therefore cannot reveal an answer —
there is nothing to reveal.

This module is deliberately the only place that decides what "student" means. If a
renderer each decided for itself, one of them would eventually disagree.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DOCUMENT_SCHEMA = "chilon.teaching_document"
DOCUMENT_SCHEMA_VERSION = "1.1.0"


class DocumentError(Exception):
    """The document cannot be built or projected as requested."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()


def _text(value: str) -> list[dict[str, str]]:
    return [{"type": "text", "value": value}]


def build_document(
    *,
    title: str,
    topic: str,
    questions: list[dict[str, Any]],
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Turn generated questions into a teaching document.

    Answers and explanations live in `teacher`-only blocks. That is the whole
    separation: nothing is duplicated into a hidden field, so there is no second
    copy to leak.
    """
    if not questions:
        raise DocumentError("cannot build a document with no questions")

    citation_ids: list[str] = []
    exercise_blocks: list[dict[str, Any]] = []

    for index, q in enumerate(questions, 1):
        ex_id = str(uuid.uuid4())
        child_blocks: list[dict[str, Any]] = [
            {
                "id": str(uuid.uuid4()),
                "type": "paragraph",
                "visibility": "student",
                "content": _text(q["stem"]),
            }
        ]

        chunk_id = q.get("citation_chunk_id")
        if chunk_id:
            citation_ids.append(chunk_id)
            child_blocks.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "citation_ref",
                    "visibility": "teacher",
                    "citation_id": chunk_id,
                }
            )

        child_blocks.append(
            {
                "id": str(uuid.uuid4()),
                "type": "answer",
                "visibility": "teacher",
                "content": _text(q.get("answer") or ""),
            }
        )
        if q.get("explanation"):
            child_blocks.append(
                {
                    "id": str(uuid.uuid4()),
                    "type": "solution",
                    "visibility": "teacher",
                    "content": _text(q["explanation"]),
                }
            )

        exercise_blocks.append(
            {
                "id": ex_id,
                "type": "exercise",
                "visibility": "student",
                "number": str(q.get("no") or index),
                "blocks": child_blocks,
            }
        )

    blocks: list[dict[str, Any]] = [
        {
            "id": str(uuid.uuid4()),
            "type": "section",
            "visibility": "student",
            "purpose": "overview",
            "title": _text(title),
            "blocks": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "paragraph",
                    "visibility": "student",
                    "content": _text(f"本讲围绕「{topic}」展开，共 {len(exercise_blocks)} 道练习。"),
                }
            ],
        },
        {
            "id": str(uuid.uuid4()),
            "type": "section",
            "visibility": "student",
            "purpose": "exercises",
            "title": _text("练习"),
            "blocks": [
                {
                    "id": str(uuid.uuid4()),
                    "type": "exercise_group",
                    "visibility": "student",
                    "blocks": exercise_blocks,
                }
            ],
        },
    ]

    return {
        "schema": DOCUMENT_SCHEMA,
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "document_id": str(uuid.uuid4()),
        "document_kind": "exercise_set",
        "metadata": {
            "title": title,
            "subject": "mathematics",
            "grade": "senior_high",
            "curriculum": "china_gaokao",
            "language": "zh-CN",
            "topics": [topic],
            "exercise_count": len(exercise_blocks),
        },
        "citations": citations or [],
        "blocks": blocks,
    }


def project(document: dict[str, Any], profile: str) -> dict[str, Any]:
    """Return the document as one audience sees it.

    `teacher` keeps everything; `student` drops every block whose visibility is not
    `student`. Dropping happens on a deep copy, so the source document is untouched
    and both versions provably come from the same source.
    """
    if profile not in ("teacher", "student"):
        raise DocumentError(f"unknown profile {profile!r}")

    doc = copy.deepcopy(document)
    if profile == "teacher":
        return doc

    def prune(node: Any) -> Any:
        if isinstance(node, dict):
            if node.get("visibility") == "teacher":
                return None
            for key, value in list(node.items()):
                if key == "blocks" and isinstance(value, list):
                    kept = [prune(child) for child in value]
                    node[key] = [c for c in kept if c is not None]
                elif isinstance(value, (dict, list)):
                    node[key] = prune(value)
            return node
        if isinstance(node, list):
            kept = [prune(item) for item in node]
            return [i for i in kept if i is not None]
        return node

    return prune(doc)


def count_blocks(node: Any, wanted: str) -> int:
    total = 0
    if isinstance(node, dict):
        if node.get("type") == wanted:
            total += 1
        for value in node.values():
            total += count_blocks(value, wanted)
    elif isinstance(node, list):
        for item in node:
            total += count_blocks(item, wanted)
    return total


async def save_draft(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document: dict[str, Any],
    *,
    title: str,
    material_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Persist a draft revision. Revisions are immutable; the draft points at the newest."""
    if material_id is None:
        material_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO materials (id, owner_id, title, document_kind, created_by)
                VALUES (:id, :owner, :title, :kind, :owner)
                """
            ),
            {"id": material_id, "owner": owner_id, "title": title, "kind": document["document_kind"]},
        )

    draft_id = (
        await session.execute(
            text("SELECT id FROM material_drafts WHERE material_id = :m LIMIT 1"),
            {"m": material_id},
        )
    ).scalar()
    if draft_id is None:
        draft_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO material_drafts (id, material_id, owner_id, created_by)
                VALUES (:id, :material, :owner, :owner)
                """
            ),
            {"id": draft_id, "material": material_id, "owner": owner_id},
        )

    revision_no = (
        await session.execute(
            text("SELECT COALESCE(max(revision_no), 0) + 1 FROM material_draft_revisions WHERE draft_id = :d"),
            {"d": draft_id},
        )
    ).scalar_one()

    digest = content_hash(document)
    revision_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO material_draft_revisions
                (id, draft_id, owner_id, revision_no, document_schema_version, content,
                 content_hash, change_origin, created_by)
            VALUES
                (:id, :draft, :owner, :no, :version, CAST(:content AS jsonb),
                 :hash, 'agent_generation', :owner)
            """
        ),
        {
            "id": revision_id,
            "draft": draft_id,
            "owner": owner_id,
            "no": revision_no,
            "version": document["schema_version"],
            "content": canonical(document),
            "hash": digest,
        },
    )
    await session.execute(
        text(
            """
            UPDATE material_drafts
            SET current_revision_id = :rev, current_revision_no = :no,
                current_content_hash = :hash, updated_at = now()
            WHERE id = :draft
            """
        ),
        {"rev": revision_id, "no": revision_no, "hash": digest, "draft": draft_id},
    )

    return {
        "material_id": str(material_id),
        "draft_id": str(draft_id),
        "revision_id": str(revision_id),
        "revision_no": revision_no,
        "content_hash": digest,
    }
