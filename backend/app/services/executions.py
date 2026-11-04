"""Execution lifecycle.

Starting an execution is not "insert a row": it is the one place where the
approval is spent. The order inside the transaction is deliberate —

1. the task must be in a state whose contract allows `start_execution`;
2. the plan version's hash must match what was approved;
3. the approval is consumed (single use, hash bound);
4. the execution row is created;
5. the task advances.

Any failure rolls all of it back, so an approval can never be half-spent.

Fencing: `agent_executions.fencing_token` increases on every lease acquisition.
A worker that lost its lease and keeps running must not be able to advance the
state machine with its stale token — its late writes are refused, not merged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract, plans, tasks

EXECUTION = contract.load("execution")


class ExecutionError(Exception):
    """Base class for execution domain errors."""


class ExecutionNotFound(ExecutionError):
    pass


class IllegalExecutionTransition(ExecutionError):
    def __init__(self, state: str, trigger: str, allowed: list[str]) -> None:
        self.state = state
        self.trigger = trigger
        self.allowed = allowed
        super().__init__(f"trigger {trigger!r} is not legal in execution state {state!r}")


class ExecutionConflict(ExecutionError):
    def __init__(self, execution_id: uuid.UUID, expected: int) -> None:
        self.execution_id = execution_id
        self.expected = expected
        super().__init__(f"execution {execution_id} is not at state_version {expected}")


class StaleFence(ExecutionError):
    """A write from a worker whose lease was taken over."""

    def __init__(self, execution_id: uuid.UUID, presented: int, current: int) -> None:
        self.execution_id = execution_id
        self.presented = presented
        self.current = current
        super().__init__(
            f"fencing token {presented} is stale for execution {execution_id} (current {current})"
        )


class LeaseUnavailable(ExecutionError):
    pass


@dataclass(frozen=True)
class Execution:
    id: uuid.UUID
    task_id: uuid.UUID
    status: str
    state_version: int
    fencing_token: int
    lease_expires_at: datetime | None


async def get_execution(session: AsyncSession, execution_id: uuid.UUID) -> Execution:
    row = (
        await session.execute(
            text(
                """
                SELECT id, task_id, status, state_version, fencing_token, lease_expires_at
                FROM agent_executions WHERE id = :id
                """
            ),
            {"id": execution_id},
        )
    ).first()
    if row is None:
        raise ExecutionNotFound(str(execution_id))
    return Execution(
        row.id, row.task_id, row.status, row.state_version, row.fencing_token, row.lease_expires_at
    )


async def start_execution(
    session: AsyncSession,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    plan_version_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    expected_task_state_version: int,
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """Spend the approval and create the execution, atomically."""
    task = await tasks.get_task(session, task_id)
    transition = tasks.TASK.trigger_for(task.status, "start_execution")
    if transition is None:
        raise tasks.IllegalTransition(
            task.status, "start_execution", tasks.allowed_triggers(task.status)
        )
    if task.state_version != expected_task_state_version:
        raise tasks.StateConflict(task_id, expected_task_state_version)

    plan_hash = (
        await session.execute(
            text(
                """
                SELECT content_hash FROM agent_plan_versions
                WHERE id = :version AND task_id = :task
                """
            ),
            {"version": plan_version_id, "task": task_id},
        )
    ).scalar()
    if plan_hash is None:
        raise plans.PlanVersionNotFound(str(plan_version_id))

    # single use + hash bound: refuses a consumed, expired or edited-away approval
    await plans.consume_for_execution(session, approval_id, plan_version_id, plan_hash)

    execution_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO agent_executions
                (id, owner_id, task_id, plan_version_id, plan_approval_id, status,
                 state_version, idempotency_key)
            VALUES
                (:id, :owner, :task, :version, :approval, :status, 0, :key)
            """
        ),
        {
            "id": execution_id,
            "owner": owner_id,
            "task": task_id,
            "version": plan_version_id,
            "approval": approval_id,
            "status": EXECUTION.initial,
            "key": idempotency_key,
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="execution",
        aggregate_id=str(execution_id),
        event_type="execution.created",
        payload={
            "execution_id": str(execution_id),
            "task_id": str(task_id),
            "plan_version_id": str(plan_version_id),
            "approval_id": str(approval_id),
        },
    )

    await tasks.advance(
        session, task_id, "start_execution", expected_state_version=expected_task_state_version
    )
    return execution_id


async def acquire_lease(
    session: AsyncSession,
    execution_id: uuid.UUID,
    worker_id: str,
    *,
    ttl_seconds: int = 30,
) -> int:
    """Take or renew the lease and bump the fencing token. Returns the new token."""
    token = (
        await session.execute(
            text(
                """
                UPDATE agent_executions
                SET lease_owner_id = :worker,
                    lease_expires_at = now() + make_interval(secs => :ttl),
                    heartbeat_at = now(),
                    fencing_token = fencing_token + 1
                WHERE id = :id
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                RETURNING fencing_token
                """
            ),
            {"id": execution_id, "worker": worker_id, "ttl": ttl_seconds},
        )
    ).scalar()
    if token is None:
        raise LeaseUnavailable(f"execution {execution_id} has a live lease")
    return int(token)


async def heartbeat(
    session: AsyncSession,
    execution_id: uuid.UUID,
    fencing_token: int,
    *,
    ttl_seconds: int = 30,
) -> None:
    result = await session.execute(
        text(
            """
            UPDATE agent_executions
            SET lease_expires_at = now() + make_interval(secs => :ttl), heartbeat_at = now()
            WHERE id = :id AND fencing_token = :token
            """
        ),
        {"id": execution_id, "token": fencing_token, "ttl": ttl_seconds},
    )
    if result.rowcount == 0:
        current = (await get_execution(session, execution_id)).fencing_token
        raise StaleFence(execution_id, fencing_token, current)


async def advance_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
    trigger: str,
    *,
    expected_state_version: int,
    fencing_token: int | None = None,
    actor_id: uuid.UUID | None = None,
) -> Execution:
    """Apply one contract transition, guarded by the contract, CAS and fencing."""
    current = await get_execution(session, execution_id)

    # Fencing is checked first, on purpose. A worker whose lease was taken over
    # is not "sending an illegal trigger" — it is no longer the owner. Reporting
    # StaleFence sends it to stop and re-read; reporting a contract violation
    # would send someone to debug the state machine instead.
    if fencing_token is not None and fencing_token != current.fencing_token:
        raise StaleFence(execution_id, fencing_token, current.fencing_token)

    transition = EXECUTION.trigger_for(current.status, trigger)
    if transition is None:
        allowed = EXECUTION.triggers_from(current.status)
        raise IllegalExecutionTransition(current.status, trigger, allowed)

    sql = """
        UPDATE agent_executions
        SET status = :to_status,
            state_version = state_version + 1,
            state_changed_at = now()
        WHERE id = :id AND state_version = :expected
    """
    params: dict = {
        "to_status": transition.to_state,
        "id": execution_id,
        "expected": expected_state_version,
    }
    if fencing_token is not None:
        sql += " AND fencing_token = :token"
        params["token"] = fencing_token

    result = await session.execute(text(sql), params)
    if result.rowcount == 0:
        raise ExecutionConflict(execution_id, expected_state_version)

    await dispatcher.enqueue(
        session,
        aggregate_type="execution",
        aggregate_id=str(execution_id),
        event_type="execution.status_changed",
        payload={
            "execution_id": str(execution_id),
            "transition": transition.id,
            "trigger": trigger,
            "from": transition.from_state,
            "to": transition.to_state,
            "actor": str(actor_id) if actor_id else None,
        },
    )
    return await get_execution(session, execution_id)
