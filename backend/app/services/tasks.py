"""Task lifecycle service.

The transition table is **read from the frozen contract**
(`schemas/state_machines.v1.json`), not transcribed into Python. That matters:
when the two disagree, the contract wins by construction, and a service that
hard-codes its own copy cannot drift silently.

Two independent protections on every transition:

* the contract decides whether (state, trigger) is legal at all;
* the CAS on `state_version` decides whether the caller saw the state it thinks
  it saw. Without the CAS, two concurrent approvals both succeed.

The outbox event is written in the same transaction as the state change, so a
crash cannot leave a state change with no event or an event with no state change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract


class TaskError(Exception):
    """Base class for task domain errors."""


class TaskNotFound(TaskError):
    pass


class IllegalTransition(TaskError):
    def __init__(self, state: str, trigger: str, allowed: list[str]) -> None:
        self.state = state
        self.trigger = trigger
        self.allowed = allowed
        super().__init__(f"trigger {trigger!r} is not legal in state {state!r}")


class StateConflict(TaskError):
    def __init__(self, task_id: uuid.UUID, expected: int) -> None:
        self.task_id = task_id
        self.expected = expected
        super().__init__(f"task {task_id} is not at state_version {expected}")


@dataclass(frozen=True)
class Task:
    id: uuid.UUID
    status: str
    state_version: int
    state_changed_at: datetime


TASK = contract.load("task")
TRANSITIONS = TASK.transitions
STATES = TASK.states
INITIAL_STATE = TASK.initial


def allowed_triggers(state: str) -> list[str]:
    return TASK.triggers_from(state)


async def create_task(
    session: AsyncSession,
    owner_id: uuid.UUID,
    title: str,
    *,
    objective: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Task:
    task_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tasks (id, owner_id, project_id, title, objective, status, created_by)
            VALUES (:id, :owner, :project, :title, :objective, :status, :created_by)
            """
        ),
        {
            "id": task_id,
            "owner": owner_id,
            "project": project_id,
            "title": title,
            "objective": objective,
            "status": INITIAL_STATE,
            "created_by": owner_id,
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="task",
        aggregate_id=str(task_id),
        event_type="task.created",
        payload={"task_id": str(task_id), "title": title, "status": INITIAL_STATE},
    )
    return Task(task_id, INITIAL_STATE, 0, datetime.now().astimezone())


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> Task:
    row = (
        await session.execute(
            text(
                """
                SELECT id, status, state_version, state_changed_at
                FROM tasks WHERE id = :id AND deleted_at IS NULL
                """
            ),
            {"id": task_id},
        )
    ).first()
    if row is None:
        raise TaskNotFound(str(task_id))
    return Task(row.id, row.status, row.state_version, row.state_changed_at)


async def advance(
    session: AsyncSession,
    task_id: uuid.UUID,
    trigger: str,
    *,
    expected_state_version: int,
    actor_id: uuid.UUID | None = None,
) -> Task:
    """Apply one contract transition, guarded by the contract and by CAS.

    Raises IllegalTransition when the contract has no such edge, StateConflict
    when the caller's view of `state_version` is stale, TaskNotFound when the row
    is gone (or belongs to someone else — RLS makes those indistinguishable,
    which is deliberate).
    """
    current = await get_task(session, task_id)

    transition = TRANSITIONS.get((current.status, trigger))
    if transition is None:
        raise IllegalTransition(current.status, trigger, allowed_triggers(current.status))

    result = await session.execute(
        text(
            """
            UPDATE tasks
            SET status = :to_status,
                state_version = state_version + 1,
                state_changed_at = now(),
                updated_at = now()
            WHERE id = :id
              AND state_version = :expected
              AND deleted_at IS NULL
            """
        ),
        {"to_status": transition.to_state, "id": task_id, "expected": expected_state_version},
    )
    if result.rowcount == 0:
        raise StateConflict(task_id, expected_state_version)

    await dispatcher.enqueue(
        session,
        aggregate_type="task",
        aggregate_id=str(task_id),
        event_type="task.status_changed",
        payload={
            "task_id": str(task_id),
            "transition": transition.id,
            "trigger": trigger,
            "from": transition.from_state,
            "to": transition.to_state,
        },
    )
    return await get_task(session, task_id)
