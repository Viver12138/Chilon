"""Teacher knowledge upload.

A teacher uploads a whole exam paper; the system records the source and a document
version. **Parsing and segmentation are not implemented here** — the version stays in
`processing` until a parser exists. That is deliberate: a version marked `indexed`
with no chunks behind it would let retrieval silently return nothing while looking
healthy.

Uploads are always `scope=teacher`, owned by the caller, `rights_status=unverified`
and `distribution_scope=private_teacher`. The platform layer is licensed content and
cannot be created through this endpoint — a teacher cannot promote their own upload
into shared material by passing a flag.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import ApiError, SessionDep, UserDep
from app.services import ingestion, knowledge_review

router = APIRouter(tags=["knowledge"], prefix="/knowledge")

UPLOAD_ROOT = Path(os.environ.get("CHILON_UPLOAD_DIR", "var/uploads"))
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_BYTES = 50 * 1024 * 1024
DEFAULT_CATEGORY_KEY = "teacher_uploads"


async def _category_for(session, owner_id: uuid.UUID) -> uuid.UUID:
    """One private 'uploads' category per teacher, created on first use."""
    existing = (
        await session.execute(
            text(
                """
                SELECT id FROM knowledge_categories
                WHERE scope = 'teacher' AND owner_id = :owner AND key = :key
                """
            ),
            {"owner": owner_id, "key": DEFAULT_CATEGORY_KEY},
        )
    ).scalar()
    if existing:
        return existing
    return (
        await session.execute(
            text(
                """
                INSERT INTO knowledge_categories (id, scope, owner_id, key, name, is_system)
                VALUES (gen_random_uuid(), 'teacher', :owner, :key, '我的上传', false)
                RETURNING id
                """
            ),
            {"owner": owner_id, "key": DEFAULT_CATEGORY_KEY},
        )
    ).scalar_one()


async def store_and_ingest(
    session,
    user: uuid.UUID,
    file: UploadFile,
    title: str,
    source_type: str,
) -> dict:
    """Validate, store and parse one upload.

    Shared by the API route and the UI page on purpose: two copies of a pipeline whose
    exit conditions (validation, lifecycle, review reasons) decide what a teacher sees
    would eventually disagree.
    """
    if file.content_type not in ALLOWED_MIME:
        raise ApiError(
            422,
            "AST_INVALID",
            f"unsupported file type {file.content_type!r}; expected PDF or DOCX",
        )
    if source_type not in ("textbook", "workbook", "gaokao_paper", "mock_exam", "other"):
        raise ApiError(422, "AST_INVALID", f"unknown source_type {source_type!r}")

    data = await file.read()
    if not data:
        raise ApiError(422, "AST_INVALID", "empty file")
    if len(data) > MAX_BYTES:
        raise ApiError(422, "AST_INVALID", f"file exceeds {MAX_BYTES // (1024 * 1024)} MB")

    category_id = await _category_for(session, user)
    checksum = hashlib.sha256(data).hexdigest()

    source_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by)
            VALUES
                (:id, 'teacher', :owner, :category, :type, :title, 'unverified',
                 'private_teacher', :owner)
            """
        ),
        {
            "id": source_id,
            "owner": user,
            "category": category_id,
            "type": source_type,
            "title": title.strip(),
        },
    )

    version_id = uuid.uuid4()
    suffix = ALLOWED_MIME[file.content_type]
    storage_key = f"uploads/{source_id}/{version_id}{suffix}"
    destination = UPLOAD_ROOT / str(source_id)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{version_id}{suffix}").write_bytes(data)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by)
            VALUES
                (:id, :source, 1, :key, :checksum, :mime, :size, 'processing', :owner)
            """
        ),
        {
            "id": version_id,
            "source": source_id,
            "key": storage_key,
            "checksum": checksum,
            "mime": file.content_type,
            "size": len(data),
            "owner": user,
        },
    )

    # parse immediately: a stored-but-unparsed paper is invisible to retrieval, and the
    # teacher would have no way to tell the difference from an empty knowledge base
    parsed = await ingestion.ingest(session, user, version_id)

    return {
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": title.strip(),
        "source_type": source_type,
        "scope": "teacher",
        "rights_status": "unverified",
        "distribution_scope": "private_teacher",
        "lifecycle_status": parsed.get("status"),
        "checksum_sha256": checksum,
        "file_size_bytes": len(data),
        "chunks": parsed.get("chunks", 0),
        "questions": parsed.get("questions", 0),
        "answers": parsed.get("answers", 0),
        "needs_review": parsed.get("needs_review", False),
        "review_reasons": parsed.get("review_reasons", []),
        "ocr": parsed.get("ocr"),
        "parse_error": parsed.get("error"),
        "parse_detail": parsed.get("detail"),
    }


@router.post("/sources", status_code=201)
async def upload_source(
    session: SessionDep,
    user: UserDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    source_type: Annotated[str, Form()] = "other",
) -> dict:
    return await store_and_ingest(session, user, file, title, source_type)


@router.get("/sources")
async def list_sources(session: SessionDep, user: UserDep) -> dict:
    """List sources with their newest version's state and the reason for it.

    The reason matters more than the state: "待复核" alone tells a teacher nothing about
    whether to re-upload a scan, add missing questions, or upload the 原卷 instead.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT s.id, s.scope, s.title, s.source_type, s.rights_status,
                       (SELECT count(*) FROM knowledge_document_versions v WHERE v.source_id = s.id) AS versions,
                       v.lifecycle_status,
                       v.parse_error,
                       v.review_reasons
                FROM knowledge_sources s
                LEFT JOIN LATERAL (
                    SELECT dv.lifecycle_status, dv.id,
                           (SELECT r.error_code FROM knowledge_ingestion_runs r
                            WHERE r.document_version_id = dv.id AND r.status = 'failed'
                            ORDER BY r.started_at DESC LIMIT 1) AS parse_error,
                           (SELECT r.metrics->'review_reasons' FROM knowledge_ingestion_runs r
                            WHERE r.document_version_id = dv.id
                            ORDER BY r.started_at DESC LIMIT 1) AS review_reasons
                    FROM knowledge_document_versions dv
                    WHERE dv.source_id = s.id
                    ORDER BY dv.version_no DESC
                    LIMIT 1
                ) v ON true
                WHERE s.deleted_at IS NULL
                ORDER BY s.created_at DESC
                LIMIT 200
                """
            )
        )
    ).all()
    return {
        "items": [
            {
                "source_id": str(r.id),
                "scope": r.scope,
                "title": r.title,
                "source_type": r.source_type,
                "rights_status": r.rights_status,
                "versions": int(r.versions),
                "lifecycle_status": r.lifecycle_status,
                "review_reasons": list(r.review_reasons or []),
                "parse_error": r.parse_error,
            }
            for r in rows
        ]
    }


@router.post("/sources/{source_id}/ingest")
async def reingest(session: SessionDep, user: UserDep, source_id: uuid.UUID) -> dict:
    """Re-run parsing for a source's newest version.

    Re-ingest replaces the chunks rather than appending, so calling it twice cannot
    double a paper's retrieval weight.
    """
    try:
        result = await ingestion.ingest_latest(session, user, source_id)
    except ingestion.IngestionError as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    return result


class ManualQuestionRequest(BaseModel):
    number: int = Field(ge=1, le=200)
    stem: str = Field(min_length=1, max_length=5000)
    answer: str | None = Field(default=None, max_length=5000)


@router.get("/versions/{version_id}")
async def version_outline(session: SessionDep, user: UserDep, version_id: uuid.UUID) -> dict:
    """Questions, numbers and the holes that still need transcribing."""
    try:
        return await knowledge_review.outline(session, user, version_id)
    except knowledge_review.ReviewNotFound as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc


@router.post("/versions/{version_id}/questions", status_code=201)
async def add_question(
    session: SessionDep,
    user: UserDep,
    version_id: uuid.UUID,
    payload: ManualQuestionRequest,
) -> dict:
    """Transcribe a question the scanner missed.

    Writes a chunk as well as a question: a question without a chunk is invisible to
    retrieval, and "I added it but it never shows up" is the bug that follows.
    """
    try:
        return await knowledge_review.add_question(
            session, user, version_id,
            number=payload.number, stem=payload.stem, answer=payload.answer,
        )
    except knowledge_review.ReviewNotFound as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    except knowledge_review.ReviewError as exc:
        raise ApiError(422, "AST_INVALID", str(exc)) from exc


@router.post("/versions/{version_id}/promote")
async def promote_version(session: SessionDep, user: UserDep, version_id: uuid.UUID) -> dict:
    """Enable retrieval for a version held for review."""
    try:
        return await knowledge_review.promote(session, user, version_id)
    except knowledge_review.ReviewNotFound as exc:
        raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    except knowledge_review.ReviewError as exc:
        raise ApiError(422, "AST_INVALID", str(exc)) from exc
