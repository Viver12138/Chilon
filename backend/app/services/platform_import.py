"""Operator import: put textbooks, Gaokao papers and mock papers into the platform corpus.

This is the P0 path. A teacher's own uploads are P1 and already work; what did not exist
was any way for **us** to populate the shared corpus, because every upload path hard-codes
`scope='teacher'` and `owner_id=<caller>`.

Three decisions worth stating:

* **It runs on an admin session.** Platform rows are written where RLS is bypassed — the
  same posture as a migration or seed. The application role can read platform content but
  never write it (the child-table policies were narrowed for exactly this).
* **Import is idempotent by checksum.** Re-running the importer over a directory must not
  create a second copy of every paper; the corpus will be re-imported many times.
* **`created_by` needs a principal and there is none yet.** `PLATFORM_PRINCIPAL` is a
  documented placeholder for the "system account" this schema still lacks; every platform
  row carries it, so the debt is visible in the data rather than hidden in a comment.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ingestion, knowledge_review

# placeholder for the system principal this schema does not have yet
PLATFORM_PRINCIPAL = uuid.UUID("00000000-0000-0000-0000-000000000001")

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

CATEGORY_BY_TYPE = {
    "textbook": ("textbooks", "教材"),
    "gaokao_paper": ("gaokao", "高考真题"),
    "mock_exam": ("mock", "模拟卷"),
    "workbook": ("workbook", "教辅"),
    "other": ("other", "其他"),
}


class ImportError_(Exception):
    pass


async def _category(session: AsyncSession, source_type: str) -> uuid.UUID:
    key, name = CATEGORY_BY_TYPE.get(source_type, CATEGORY_BY_TYPE["other"])
    existing = (
        await session.execute(
            text(
                "SELECT id FROM knowledge_categories "
                "WHERE scope = 'platform' AND owner_id IS NULL AND key = :k"
            ),
            {"k": key},
        )
    ).scalar()
    if existing:
        return existing
    return (
        await session.execute(
            text(
                """
                INSERT INTO knowledge_categories (id, scope, owner_id, key, name, is_system)
                VALUES (gen_random_uuid(), 'platform', NULL, :k, :n, true)
                RETURNING id
                """
            ),
            {"k": key, "n": name},
        )
    ).scalar_one()


async def already_imported(session: AsyncSession, checksum: str) -> dict | None:
    row = (
        await session.execute(
            text(
                """
                SELECT v.id, v.lifecycle_status, s.title
                FROM knowledge_document_versions v
                JOIN knowledge_sources s ON s.id = v.source_id
                WHERE s.scope = 'platform' AND v.checksum_sha256 = :c
                LIMIT 1
                """
            ),
            {"c": checksum},
        )
    ).first()
    if row is None:
        return None
    return {
        "document_version_id": str(row.id),
        "lifecycle_status": row.lifecycle_status,
        "title": row.title,
    }


async def import_document(
    session: AsyncSession,
    *,
    path: Path,
    title: str,
    source_type: str = "gaokao_paper",
    accept: bool = True,
) -> dict[str, Any]:
    """Import one file into the platform corpus. Returns a summary either way."""
    if not path.exists():
        raise ImportError_(f"no such file: {path}")
    suffix = path.suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise ImportError_(f"unsupported file type {suffix!r}")

    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()

    existing = await already_imported(session, checksum)
    if existing:
        # re-running the importer must not duplicate the corpus
        return {"skipped": True, "reason": "checksum already imported", **existing}

    category_id = await _category(session, source_type)
    source_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by, rights_note, year, exam_paper)
            VALUES
                (:id, 'platform', NULL, :category, :type, :title, 'licensed',
                 'classroom', :principal, :note, :year, :paper)
            """
        ),
        {
            "id": source_id,
            "category": category_id,
            "type": source_type,
            "title": title,
            "principal": PLATFORM_PRINCIPAL,
            "note": "operator import; rights to be confirmed before republishing",
            "year": parse_exam_meta(title)[0],
            "paper": parse_exam_meta(title)[1],
        },
    )

    version_id = uuid.uuid4()
    storage_key = f"uploads/{source_id}/{version_id}{suffix}"
    destination = Path(ingestion.UPLOAD_ROOT) / storage_key.split("uploads/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by)
            VALUES (:id, :source, 1, :key, :hash, :mime, :size, 'processing', :principal)
            """
        ),
        {
            "id": version_id,
            "source": source_id,
            "key": storage_key,
            "hash": checksum,
            "mime": mime,
            "size": len(data),
            "principal": PLATFORM_PRINCIPAL,
        },
    )

    parsed = await ingestion.ingest(session, PLATFORM_PRINCIPAL, version_id)

    promoted = None
    if accept and parsed.get("status") == "pending_review":
        # the operator reviewed the run summary, not a human in the UI; recording that is
        # what `promote` writes
        promoted = await knowledge_review.promote(session, PLATFORM_PRINCIPAL, version_id)

    return {
        "skipped": False,
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": title,
        "scope": "platform",
        "status": parsed.get("status"),
        "questions": parsed.get("questions", 0),
        "chunks": parsed.get("chunks", 0),
        "review_reasons": parsed.get("review_reasons", []),
        # a failed import must say why; "0 questions" is a symptom, not a reason
        "detail": parsed.get("detail") or parsed.get("error") or "",
        "promoted": bool(promoted and promoted.get("promoted")),
    }
