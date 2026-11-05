"""Import OCR'd mock papers as questions, using the paper-cut action only.

A mock paper is a question paper, so — unlike a textbook — its value is the 题, cut into
retrievable items. The cut action returns one block per question, and `ingestion.ingest`
already handles the rest: fragment merging, gap detection, question typing and the
`pending_review` decision.

A whole-page route (`RecognizeEduPaperOcr` plus slicing at question boundaries) was
written, unit-tested and then **removed**: it was never measured against a real call, and
unproven code kept in the tree gets used. Only the measured route stays.

Measured quality (5 papers, 26 pages): **63 questions**, i.e. 10, 11, 13, 14 and 15 per
paper against roughly 19 — 4 to 9 are still missed. That is the vendor's cutting, the same
limit the scanned Gaokao papers hit.

Provenance: these come from a community file space, not a licensed provider. They are
stored as `restricted` with a note saying so: "the user does not care where it came from"
is a decision about risk, not a statement about rights.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ingestion, knowledge_review
from app.services.platform_import import PLATFORM_PRINCIPAL, _category

ATTRIBUTION = (
    "笔袋（gaojiua.com）共享空间「官方资料总库/优质模拟」的用户上传文件；"
    "来源与授权状态未能核实，仅作内部教研使用，不得再分发"
)


async def already_imported(session: AsyncSession, checksum: str) -> uuid.UUID | None:
    return (
        await session.execute(
            text(
                """
                SELECT v.id FROM knowledge_document_versions v
                JOIN knowledge_sources s ON s.id = v.source_id
                WHERE s.scope = 'platform' AND v.checksum_sha256 = :c LIMIT 1
                """
            ),
            {"c": checksum},
        )
    ).scalar()


async def import_mock_paper(
    session: AsyncSession,
    *,
    path: Path,
    title: str,
    accept: bool = True,
) -> dict[str, Any]:
    """Import one mock paper through the same OCR path the scanned Gaokao papers use."""
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    existing = await already_imported(session, checksum)
    if existing:
        return {"skipped": True, "document_version_id": str(existing), "title": title}

    category_id = await _category(session, "mock_exam")
    source_id = uuid.uuid4()
    version_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by, rights_note)
            VALUES (:id, 'platform', NULL, :category, 'mock_exam', :title, 'restricted',
                    'classroom', :principal, :note)
            """
        ),
        {
            "id": source_id,
            "category": category_id,
            "title": title,
            "principal": PLATFORM_PRINCIPAL,
            "note": ATTRIBUTION,
        },
    )

    storage_key = f"uploads/{source_id}/{version_id}.pdf"
    destination = Path(ingestion.UPLOAD_ROOT) / storage_key.split("uploads/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by)
            VALUES (:id, :source, 1, :key, :hash, 'application/pdf', :size,
                    'processing', :principal)
            """
        ),
        {
            "id": version_id,
            "source": source_id,
            "key": storage_key,
            "hash": checksum,
            "size": len(raw),
            "principal": PLATFORM_PRINCIPAL,
        },
    )

    parsed = await ingestion.ingest(session, PLATFORM_PRINCIPAL, version_id)
    promoted = False
    if accept and parsed.get("status") == "pending_review":
        await knowledge_review.promote(session, PLATFORM_PRINCIPAL, version_id)
        promoted = True

    return {
        "skipped": False,
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": title,
        "pages": (parsed.get("ocr") or {}).get("pages", 0),
        "questions": parsed.get("questions", 0),
        "status": parsed.get("status"),
        "promoted": promoted,
        "gaps": (parsed.get("ocr") or {}).get("gaps", []),
    }
