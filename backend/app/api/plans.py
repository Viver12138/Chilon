"""Plan, requirement and approval endpoints from the frozen surface.

Three small routers rather than one, because each has its own aggregate and its own
error behaviour. They all share one rule: **the transition is looked up in the
contract, never written as an if/else here**.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import ApiError, SessionDep, UserDep
from app.services import contract, plans

router = APIRouter(tags=["plans"])


class TransitionRequest(BaseModel):
    expected_state_version: int | None = None
    reason: str | None = None


async def _transition(
    session,
    table: str,
    row_id: uuid.UUID,
    aggregate: str,
    trigger: str,
    *,
    actor_column: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> str:
    """Apply one contract transition to a simple status column."""
    spec = contract.load(aggregate)
    current = (
        await session.execute(text(f"SELECT status FROM {table} WHERE id = :id"), {"id": row_id})
    ).scalar()
    if current is None:
        raise ApiError(404, "NOT_FOUND", f"{table} {row_id} not found")

    transition = spec.trigger_for(current, trigger)
    if transition is None:
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"trigger {trigger!r} is not legal in {aggregate} state {current!r}",
        )

    assignments = ["status = :status"]
    params: dict[str, Any] = {"status": transition.to_state, "id": row_id, "current": current}
    if actor_column and actor_id:
        assignments.append(f"{actor_column} = :actor")
        params["actor"] = actor_id
    await session.execute(
        text(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = :id AND status = :current"),
        params,
    )
    return transition.to_state


@router.post("/requirement-versions/{requirement_version_id}/actions/abandon")
async def abandon_requirement(
    requirement_version_id: uuid.UUID, session: SessionDep, user: UserDep
) -> dict:
    status = await _transition(
        session,
        "task_requirement_versions",
        requirement_version_id,
        "requirement_version",
        "abandon",
    )
    return {"id": str(requirement_version_id), "status": status}


@router.post("/plan-versions/{plan_version_id}/actions/reject")
async def reject_plan_version(
    plan_version_id: uuid.UUID,
    payload: TransitionRequest | None = None,
    session: SessionDep = None,
    user: UserDep = None,
) -> dict:
    status = await _transition(
        session, "agent_plan_versions", plan_version_id, "plan_version", "reject"
    )
    return {"id": str(plan_version_id), "status": status}


@router.post("/plan-approvals/{plan_approval_id}/actions/revoke")
async def revoke_approval(plan_approval_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    """Revoke an approval. A consumed approval cannot be revoked — it already ran."""
    consumed = (
        await session.execute(
            text("SELECT consumed_at FROM agent_plan_approvals WHERE id = :id"),
            {"id": plan_approval_id},
        )
    ).scalar()
    if consumed is not None:
        raise ApiError(409, "APPROVAL_CONSUMED", "approval was already consumed by an execution")

    status = await _transition(
        session,
        "agent_plan_approvals",
        plan_approval_id,
        "plan_approval",
        "revoke",
        actor_column="approver_id",
        actor_id=user,
    )
    return {"id": str(plan_approval_id), "status": status}


@router.get("/plan-approvals/{plan_approval_id}")
async def get_approval(plan_approval_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    row = (
        await session.execute(
            text(
                """
                SELECT id, plan_version_id, status, plan_content_hash, consumed_at, expires_at
                FROM agent_plan_approvals WHERE id = :id
                """
            ),
            {"id": plan_approval_id},
        )
    ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "approval not found")
    return {
        "id": str(row.id),
        "plan_version_id": str(row.plan_version_id),
        "status": row.status,
        "plan_content_hash": row.plan_content_hash,
        "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.post("/plan-approvals/{plan_approval_id}/actions/approve")
async def approve(plan_approval_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    """Approve. Not in D5's 23 action endpoints (which only lists reject/revoke);
    exposed here because `decide()` already existed and a surface without it cannot
    complete the golden path. Flagged as a contract gap rather than hidden."""
    await plans.decide(session, plan_approval_id, user, "approved")
    return {"id": str(plan_approval_id), "status": "approved"}
