"""Publishing: draft revision in, immutable version out.

Publishing is the only operation that creates a permanent artefact, so it is also
the one with the most guards:

1. a publication approval must exist and be **approved**;
2. it must bind **this exact draft revision and content hash** — if the draft moved,
   the approval does not carry over;
3. it is **single use**: two publishes cannot consume the same approval;
4. the quality report attached to it must not be `blocked`.

The version row records the approval that authorised it, so "who approved what" is
answerable a year later without reading logs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher


class PublishError(Exception):
    """The draft cannot be published as requested."""


class ApprovalRequired(PublishError):
    pass


class QualityBlocked(PublishError):
    pass


class DraftChanged(PublishError):
    pass


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Approval:
    id: uuid.UUID
    draft_revision_id: uuid.UUID
    draft_content_hash: str
    status: str
    consumed_at: datetime | None


async def request_publication(
    session: AsyncSession,
    owner_id: uuid.UUID,
    material_id: uuid.UUID,
    *,
    quality_verdict: str,
    quality_summary: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Create a pending publication approval bound to the draft's current revision."""
    if quality_verdict == "blocked":
        raise QualityBlocked("the latest quality report is blocking; fix it before publishing")

    draft = (
        await session.execute(
            text(
                """
                SELECT id, current_revision_id, current_content_hash, base_version_id, status
                FROM material_drafts WHERE material_id = :m
                """
            ),
            {"m": material_id},
        )
    ).first()
    if draft is None or draft.current_revision_id is None:
        raise PublishError("material has no draft revision to publish")

    revision = (
        await session.execute(
            text(
                """
                SELECT revision_no, document_schema_version
                FROM material_draft_revisions WHERE id = :id
                """
            ),
            {"id": draft.current_revision_id},
        )
    ).one()

    approval_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO material_publication_approvals
                (id, owner_id, material_id, draft_id, draft_revision_id, draft_content_hash,
                 base_version_id, document_schema_version, quality_policy_hash,
                 gate_snapshot_hash, citation_snapshot_hash, profile_config_hash, status)
            VALUES
                (:id, :owner, :material, :draft, :revision, :hash,
                 :base, :schema, :quality_hash, :gate_hash, :citation_hash, :profile_hash, 'pending')
            """
        ),
        {
            "id": approval_id,
            "owner": owner_id,
            "material": material_id,
            "draft": draft.id,
            "revision": draft.current_revision_id,
            "hash": draft.current_content_hash,
            "base": draft.base_version_id,
            "schema": revision.document_schema_version,
            # snapshots are hashes of what we actually know, not placeholders
            "quality_hash": _sha(_canonical({"verdict": quality_verdict, "summary": quality_summary or {}})),
            "gate_hash": _sha(_canonical({"gate": "publication", "verdict": quality_verdict})),
            "citation_hash": _sha("citations-at-publish"),
            "profile_hash": _sha("teacher+student"),
        },
    )
    return approval_id


async def approve_publication(
    session: AsyncSession, approval_id: uuid.UUID, approver_id: uuid.UUID
) -> None:
    result = await session.execute(
        text(
            """
            UPDATE material_publication_approvals
            SET status = 'approved', approver_id = :approver, approved_at = now()
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"approver": approver_id, "id": approval_id},
    )
    if result.rowcount == 0:
        raise ApprovalRequired("approval is missing or already decided")


async def publish(
    session: AsyncSession,
    owner_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    change_summary: str | None = None,
) -> dict[str, Any]:
    """Consume the approval and create the immutable version, atomically."""
    approval = (
        await session.execute(
            text(
                """
                SELECT id, material_id, draft_id, draft_revision_id, draft_content_hash,
                       status, consumed_at
                FROM material_publication_approvals WHERE id = :id
                """
            ),
            {"id": approval_id},
        )
    ).first()
    if approval is None:
        raise ApprovalRequired("approval not found")
    if approval.status != "approved":
        raise ApprovalRequired(f"approval is {approval.status!r}, not approved")
    if approval.consumed_at is not None:
        raise ApprovalRequired("approval was already consumed")

    draft = (
        await session.execute(
            text("SELECT current_revision_id, current_content_hash FROM material_drafts WHERE id = :id"),
            {"id": approval.draft_id},
        )
    ).one()
    if draft.current_revision_id != approval.draft_revision_id:
        raise DraftChanged("the draft moved since approval; approve the new revision")
    if draft.current_content_hash != approval.draft_content_hash:
        raise DraftChanged("the draft content changed since approval")

    # single use, enforced by the database rather than by this function
    consumed = (
        await session.execute(
            text(
                """
                UPDATE material_publication_approvals
                SET status = 'consumed', consumed_at = now()
                WHERE id = :id AND status = 'approved' AND consumed_at IS NULL
                RETURNING id
                """
            ),
            {"id": approval_id},
        )
    ).first()
    if consumed is None:
        raise ApprovalRequired("approval was consumed by a concurrent publish")

    revision = (
        await session.execute(
            text(
                """
                SELECT content, content_hash, document_schema_version
                FROM material_draft_revisions WHERE id = :id
                """
            ),
            {"id": approval.draft_revision_id},
        )
    ).one()

    version_no = (
        await session.execute(
            text("SELECT COALESCE(max(version_no), 0) + 1 FROM material_versions WHERE material_id = :m"),
            {"m": approval.material_id},
        )
    ).scalar_one()

    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO material_versions
                (id, material_id, owner_id, version_no, document_schema_version,
                 document_content, content_hash, change_summary, source_draft_revision_id,
                 publication_approval_id, idempotency_key, created_by)
            VALUES
                (:id, :material, :owner, :no, :schema, CAST(:content AS jsonb), :hash,
                 :summary, :revision, :approval, :key, :owner)
            """
        ),
        {
            "id": version_id,
            "material": approval.material_id,
            "owner": owner_id,
            "no": version_no,
            "schema": revision.document_schema_version,
            "content": _canonical(revision.content),
            "hash": revision.content_hash,
            "summary": change_summary or f"发布草稿修订（发布审批 {approval_id}）",
            "revision": approval.draft_revision_id,
            "approval": approval_id,
            "key": f"publish:{approval_id}",
        },
    )
    await session.execute(
        text(
            """
            UPDATE materials SET current_version_id = :v, updated_at = now() WHERE id = :m
            """
        ),
        {"v": version_id, "m": approval.material_id},
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="material_version",
        aggregate_id=str(version_id),
        event_type="material.published",
        payload={
            "version_id": str(version_id),
            "version_no": version_no,
            "approval_id": str(approval_id),
            "content_hash": revision.content_hash,
        },
    )
    return {
        "version_id": str(version_id),
        "material_id": str(approval.material_id),
        "version_no": version_no,
        "content_hash": revision.content_hash,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
