"""Execution endpoints from the frozen surface."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep, UserDep
from app.services import contract, executions

router = APIRouter(tags=["executions"])


class ActionRequest(BaseModel):
    expected_state_version: int
    fencing_token: int | None = None


def _execution_json(execution: executions.Execution) -> dict:
    return {
        "id": str(execution.id),
        "task_id": str(execution.task_id),
        "status": execution.status,
        "state_version": execution.state_version,
        "fencing_token": execution.fencing_token,
        "allowed_triggers": executions.EXECUTION.triggers_from(execution.status),
    }


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    execution = await executions.get_execution(session, execution_id)
    return _execution_json(execution)


@router.post("/executions/{execution_id}/actions/request-pause")
async def request_pause(
    execution_id: uuid.UUID, payload: ActionRequest, session: SessionDep, user: UserDep
) -> dict:
    execution = await executions.advance_execution(
        session,
        execution_id,
        "request_pause",
        expected_state_version=payload.expected_state_version,
        fencing_token=payload.fencing_token,
        actor_id=user,
    )
    return _execution_json(execution)


@router.post("/executions/{execution_id}/actions/resume")
async def resume(
    execution_id: uuid.UUID, payload: ActionRequest, session: SessionDep, user: UserDep
) -> dict:
    execution = await executions.advance_execution(
        session,
        execution_id,
        "resume",
        expected_state_version=payload.expected_state_version,
        fencing_token=payload.fencing_token,
        actor_id=user,
    )
    return _execution_json(execution)


@router.get("/executions/{execution_id}/steps")
async def list_steps(execution_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    """Not in D5. Exposed because the step DAG is unusable without a read path;
    recorded as a contract gap rather than silently pretended to exist."""
    from sqlalchemy import text

    from app.services import steps

    ready = await steps.ready_steps(session, execution_id)
    rows = (
        await session.execute(
            text(
                """
                SELECT s.step_key, s.title, s.ordinal, se.status, se.error_code
                FROM agent_plan_steps s
                JOIN agent_executions e ON e.plan_version_id = s.plan_version_id
                LEFT JOIN agent_step_executions se
                       ON se.plan_step_id = s.id AND se.execution_id = e.id
                WHERE e.id = :exec
                ORDER BY s.ordinal
                """
            ),
            {"exec": execution_id},
        )
    ).all()
    return {
        "items": [
            {
                "step_key": r.step_key,
                "title": r.title,
                "ordinal": r.ordinal,
                "status": r.status or "pending",
                "error_code": r.error_code,
            }
            for r in rows
        ],
        "ready": [r["step_key"] for r in ready],
        "states": contract.load("step_execution").states,
    }
