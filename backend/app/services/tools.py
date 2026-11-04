"""Tool invocation: the five gates before a tool call is allowed to happen.

Master §15.3 requires every tool call to pass Identity, Owner, Scope, Capability
and Business Approval. This module implements the parts that belong to the data
layer:

* **Capability** — `agent_tool_grants` must contain an active grant for this owner;
* **Business approval** — a tool flagged `requires_approval` may only run inside an
  execution that came from an approved plan;
* **Idempotency** — the key is derived from execution + step + tool + version +
  canonical args, so a retried call returns the original result instead of
  performing the side effect twice.

Identity and scope are enforced by RLS on the owning session, not here: a service
that re-checks them would be duplicating a guarantee the database already makes.

`tool_version` participates in the key (master §21.6). If the tool is upgraded
mid-run, the retry is a *different* call — that is intentional: silently reusing a
result produced by different code would claim a guarantee we do not have.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract

TOOL = contract.load("tool_execution")


class ToolError(Exception):
    """Base class for tool invocation errors."""


class ToolNotFound(ToolError):
    pass


class ToolDisabled(ToolError):
    pass


class ToolNotGranted(ToolError):
    pass


class ToolApprovalRequired(ToolError):
    pass


class ToolConflict(ToolError):
    pass


@dataclass(frozen=True)
class Invocation:
    id: uuid.UUID
    status: str
    idempotency_key: str
    replayed: bool


def canonical_args(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def idempotency_key(
    execution_id: uuid.UUID,
    step_execution_id: uuid.UUID | None,
    tool_key: str,
    tool_version: str,
    args: dict,
) -> str:
    """Stable across retries, different across any meaningful change."""
    parts = [
        str(execution_id),
        str(step_execution_id or ""),
        tool_key,
        tool_version,
        canonical_args(args),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


async def invoke(
    session: AsyncSession,
    execution_id: uuid.UUID,
    tool_key: str,
    args: dict,
    *,
    step_execution_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Invocation:
    """Record one tool call, or return the existing record for a replay."""
    tool = (
        await session.execute(
            text(
                """
                SELECT id, key, version, is_enabled, requires_approval
                FROM agent_tool_definitions
                WHERE key = :key
                ORDER BY is_enabled DESC, version DESC
                LIMIT 1
                """
            ),
            {"key": tool_key},
        )
    ).first()
    if tool is None:
        raise ToolNotFound(tool_key)
    if not tool.is_enabled:
        raise ToolDisabled(tool_key)

    owner_id = (
        await session.execute(
            text("SELECT owner_id FROM agent_executions WHERE id = :id"), {"id": execution_id}
        )
    ).scalar()
    if owner_id is None:
        raise ToolError(f"execution {execution_id} not found")

    granted = (
        await session.execute(
            text(
                """
                SELECT 1 FROM agent_tool_grants
                WHERE owner_id = :owner AND tool_definition_id = :tool AND revoked_at IS NULL
                """
            ),
            {"owner": owner_id, "tool": tool.id},
        )
    ).first()
    if granted is None:
        raise ToolNotGranted(f"{tool_key} is not granted to this owner")

    if tool.requires_approval:
        # the execution already proved it came from an approved plan; re-assert it
        # here because a tool can be flagged later, after the execution started
        approved = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM agent_executions e
                    JOIN agent_plan_approvals a ON a.id = e.plan_approval_id
                    WHERE e.id = :exec AND a.status = 'approved'
                    """
                ),
                {"exec": execution_id},
            )
        ).first()
        if approved is None:
            raise ToolApprovalRequired(f"{tool_key} requires an approved plan")

    key = idempotency_key(execution_id, step_execution_id, tool.key, tool.version, args)
    invocation_id = uuid.uuid4()

    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO agent_tool_executions
                    (id, execution_id, step_execution_id, tool_definition_id, tool_version,
                     idempotency_key, args_hash, status)
                VALUES
                    (:id, :exec, :step, :tool, :version, :key, :args_hash, :status)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id, status
                """
            ),
            {
                "id": invocation_id,
                "exec": execution_id,
                "step": step_execution_id,
                "tool": tool.id,
                "version": tool.version,
                "key": key,
                "args_hash": hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest(),
                "status": TOOL.initial,
            },
        )
    ).first()

    if inserted is None:
        existing = (
            await session.execute(
                text(
                    "SELECT id, status FROM agent_tool_executions WHERE idempotency_key = :k"
                ),
                {"k": key},
            )
        ).one()
        return Invocation(existing.id, existing.status, key, replayed=True)

    await dispatcher.enqueue(
        session,
        aggregate_type="tool_execution",
        aggregate_id=str(invocation_id),
        event_type="tool.requested",
        payload={
            "tool_key": tool.key,
            "tool_version": tool.version,
            "execution_id": str(execution_id),
            "idempotency_key": key,
            "actor": str(actor_id) if actor_id else None,
        },
    )
    return Invocation(inserted.id, inserted.status, key, replayed=False)


async def advance(
    session: AsyncSession,
    invocation_id: uuid.UUID,
    trigger: str,
    *,
    expected_state_version: int | None = None,
) -> str:
    """Move one tool execution along its contract.

    `agent_tool_executions` has no `state_version` column (the contract's tool
    machine is driven by explicit triggers, not by optimistic concurrency), so the
    guard here is the current status alone.
    """
    current = (
        await session.execute(
            text("SELECT status FROM agent_tool_executions WHERE id = :id"), {"id": invocation_id}
        )
    ).scalar()
    if current is None:
        raise ToolNotFound(str(invocation_id))

    transition = TOOL.trigger_for(current, trigger)
    if transition is None:
        raise ToolConflict(
            f"trigger {trigger!r} is not legal in tool state {current!r}"
        )

    await session.execute(
        text("UPDATE agent_tool_executions SET status = :status WHERE id = :id AND status = :current"),
        {"status": transition.to_state, "id": invocation_id, "current": current},
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="tool_execution",
        aggregate_id=str(invocation_id),
        event_type="tool.status_changed",
        payload={"transition": transition.id, "from": current, "to": transition.to_state},
    )
    return transition.to_state


async def record_result(
    session: AsyncSession,
    invocation_id: uuid.UUID,
    result: dict | None,
    *,
    succeeded: bool,
    error_code: str | None = None,
) -> None:
    """Attach the outcome. The result hash lets a later reader verify the payload."""
    payload = canonical_args(result or {})
    await session.execute(
        text(
            """
            UPDATE agent_tool_executions
            SET result = CAST(:result AS jsonb),
                result_hash = :hash,
                status = :status,
                error_code = :err,
                finished_at = now()
            WHERE id = :id
            """
        ),
        {
            "result": payload,
            "hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "status": "succeeded" if succeeded else "failed",
            "err": error_code,
            "id": invocation_id,
        },
    )
