"""Plan versioning and plan approval.

The product contract is "the agent proposes, the teacher approves". Two rules make
that meaningful, and both are enforced in one SQL statement rather than in
application logic:

* an approval authorises **one** execution (single consumption);
* it authorises **that exact plan content** (hash binding). If the plan changes
  after approval, the approval must not carry over.

`consume_for_execution` does the whole check as a conditional UPDATE ... RETURNING.
A read-then-write would race: two executors could both read "approved, unconsumed"
and both proceed. The database decides, once.

Consumption is a *use*, not a *decision*, so it sets `consumed_at` and leaves the
status at `approved` — the contract's state list has no `consumed` state, and the
CHECK constraint ties `consumed_at` to `status = 'approved'`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract, steps

PLAN_VERSION = contract.load("plan_version")
PLAN_APPROVAL = contract.load("plan_approval")


class PlanError(Exception):
    """Base class for plan domain errors."""


class PlanVersionNotFound(PlanError):
    pass


class ApprovalNotFound(PlanError):
    pass


class ApprovalNotConsumable(PlanError):
    """The approval exists but cannot authorise this execution."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"approval is not consumable: {reason}")


def content_hash(content: dict) -> str:
    """Canonical hash: key order must not change the identity of a plan."""
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlanVersion:
    id: uuid.UUID
    plan_id: uuid.UUID
    version_no: int
    status: str
    content_hash: str


async def create_plan_version(
    session: AsyncSession,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    requirement_version_id: uuid.UUID,
    content: dict,
) -> PlanVersion:
    # One plan per task: look it up first, create only when absent. The previous
    # version inserted unconditionally with ON CONFLICT (id), which can never fire
    # because the id is freshly generated — every call made a new plan and every
    # plan started numbering at 1.
    plan_id = (
        await session.execute(
            text("SELECT id FROM agent_plans WHERE task_id = :task_id ORDER BY created_at LIMIT 1"),
            {"task_id": task_id},
        )
    ).scalar()

    if plan_id is None:
        plan_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO agent_plans (id, task_id, owner_id, status)
                    VALUES (gen_random_uuid(), :task_id, :owner_id, 'draft')
                    RETURNING id
                    """
                ),
                {"task_id": task_id, "owner_id": owner_id},
            )
        ).scalar_one()

    version_no = (
        await session.execute(
            text("SELECT COALESCE(max(version_no), 0) + 1 FROM agent_plan_versions WHERE plan_id = :p"),
            {"p": plan_id},
        )
    ).scalar_one()

    digest = content_hash(content)
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO agent_plan_versions
                (id, plan_id, task_id, owner_id, version_no, requirement_version_id,
                 content, content_hash, status, created_by)
            VALUES
                (:id, :plan_id, :task_id, :owner_id, :version_no, :req,
                 CAST(:content AS jsonb), :hash, :status, :owner_id)
            """
        ),
        {
            "id": version_id,
            "plan_id": plan_id,
            "task_id": task_id,
            "owner_id": owner_id,
            "version_no": version_no,
            "req": requirement_version_id,
            "content": json.dumps(content, ensure_ascii=False),
            "hash": digest,
            "status": PLAN_VERSION.initial,
        },
    )
    await session.execute(
        text("UPDATE agent_plans SET latest_version_id = :v, updated_at = now() WHERE id = :p"),
        {"v": version_id, "p": plan_id},
    )
    # Validate and materialise the DAG here, not at execution time: an
    # unexecutable plan must never reach the approval screen.
    await steps.materialise(session, version_id, content)
    await dispatcher.enqueue(
        session,
        aggregate_type="plan_version",
        aggregate_id=str(version_id),
        event_type="plan.version_created",
        payload={"plan_version_id": str(version_id), "version_no": version_no, "content_hash": digest},
    )
    return PlanVersion(version_id, plan_id, version_no, PLAN_VERSION.initial, digest)


async def request_approval(
    session: AsyncSession,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    plan_version_id: uuid.UUID,
    *,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    row = (
        await session.execute(
            text(
                """
                SELECT plan_id, content_hash, status
                FROM agent_plan_versions WHERE id = :id
                """
            ),
            {"id": plan_version_id},
        )
    ).first()
    if row is None:
        raise PlanVersionNotFound(str(plan_version_id))

    approval_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO agent_plan_approvals
                (id, owner_id, task_id, plan_id, plan_version_id, plan_content_hash,
                 status, expires_at)
            VALUES
                (:id, :owner_id, :task_id, :plan_id, :version_id, :hash, 'pending', :expires_at)
            """
        ),
        {
            "id": approval_id,
            "owner_id": owner_id,
            "task_id": task_id,
            "plan_id": row.plan_id,
            "version_id": plan_version_id,
            "hash": row.content_hash,
            "expires_at": expires_at,
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="plan_approval",
        aggregate_id=str(approval_id),
        event_type="plan.approval_requested",
        payload={"approval_id": str(approval_id), "plan_version_id": str(plan_version_id)},
    )
    return approval_id


async def decide(
    session: AsyncSession,
    approval_id: uuid.UUID,
    approver_id: uuid.UUID,
    decision: str,
) -> None:
    """Approve or reject. CAS on `status = 'pending'` so a second decision cannot win."""
    if decision not in ("approved", "rejected"):
        raise PlanError(f"invalid decision {decision!r}")
    result = await session.execute(
        text(
            """
            UPDATE agent_plan_approvals
            SET status = :decision, approver_id = :approver, approved_at = now()
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"decision": decision, "approver": approver_id, "id": approval_id},
    )
    if result.rowcount == 0:
        raise ApprovalNotConsumable("already decided or missing")
    await dispatcher.enqueue(
        session,
        aggregate_type="plan_approval",
        aggregate_id=str(approval_id),
        event_type=f"plan.approval_{decision}",
        payload={"approval_id": str(approval_id), "decision": decision},
    )


async def consume_for_execution(
    session: AsyncSession,
    approval_id: uuid.UUID,
    plan_version_id: uuid.UUID,
    expected_hash: str,
    *,
    now: datetime | None = None,
) -> None:
    """Atomically mark the approval used, refusing anything that no longer fits.

    Order of checks matters for the error message, not for safety: the UPDATE's
    WHERE clause is what actually guarantees correctness.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT status, consumed_at, plan_version_id, plan_content_hash, expires_at
                FROM agent_plan_approvals WHERE id = :id
                """
            ),
            {"id": approval_id},
        )
    ).first()
    if row is None:
        raise ApprovalNotFound(str(approval_id))
    if row.status != "approved":
        raise ApprovalNotConsumable(f"status is {row.status}")
    if row.consumed_at is not None:
        raise ApprovalNotConsumable("already consumed")
    if row.plan_version_id != plan_version_id:
        raise ApprovalNotConsumable("approval is for a different plan version")
    if row.plan_content_hash != expected_hash:
        raise ApprovalNotConsumable("plan content changed since approval")
    current = now or datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= current:
        raise ApprovalNotConsumable("expired")

    result = await session.execute(
        text(
            """
            UPDATE agent_plan_approvals
            SET consumed_at = now()
            WHERE id = :id
              AND status = 'approved'
              AND consumed_at IS NULL
              AND plan_content_hash = :hash
              AND plan_version_id = :version
            RETURNING id
            """
        ),
        {"id": approval_id, "hash": expected_hash, "version": plan_version_id},
    )
    if result.first() is None:
        raise ApprovalNotConsumable("lost the race to another consumer")

    await dispatcher.enqueue(
        session,
        aggregate_type="plan_approval",
        aggregate_id=str(approval_id),
        event_type="plan.approval_consumed",
        payload={"approval_id": str(approval_id), "plan_version_id": str(plan_version_id)},
    )
