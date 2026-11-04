"""Task endpoints, named exactly as `schemas/api_surface.v1.json` declares them.

The contract spells actions in kebab-case (`submit-requirement`) while the state
machine uses snake_case (`submit_requirement`). That translation lives here, in one
place, because it is the seam between two frozen contracts — a mismatch must be a
one-line change, not a hunt.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import SessionDep, UserDep
from app.services import contract, tasks

router = APIRouter(tags=["tasks"])

ACTION_TO_TRIGGER = {
    "submit-requirement": "submit_requirement",
    "approve-plan": "approve_plan",
    "request-plan-revision": "request_plan_revision",
    "cancel": "cancel",
    "replan": "replan",
    "retry": "retry",
    "request-cancel": "request_cancel",
}


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    objective: str | None = None
    project_id: uuid.UUID | None = None


class ActionRequest(BaseModel):
    expected_state_version: int
    # accepted so the same client code can drive every action endpoint
    body: dict[str, Any] | None = None


def _task_json(task: tasks.Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "status": task.status,
        "state_version": task.state_version,
        "state_changed_at": task.state_changed_at.isoformat(),
        "allowed_actions": sorted(
            f"/tasks/{{task_id}}/actions/{trigger.replace('_', '-')}"
            for trigger in tasks.allowed_triggers(task.status)
            if trigger in ACTION_TO_TRIGGER.values()
        ),
    }


@router.post("/tasks", status_code=201)
async def create_task(payload: CreateTaskRequest, session: SessionDep, user: UserDep) -> dict:
    task = await tasks.create_task(
        session, user, payload.title, objective=payload.objective, project_id=payload.project_id
    )
    return _task_json(task)


@router.get("/tasks")
async def list_tasks(session: SessionDep, user: UserDep) -> dict:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, title, status, state_version, updated_at
                FROM tasks WHERE deleted_at IS NULL
                ORDER BY updated_at DESC LIMIT 100
                """
            )
        )
    ).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "title": r.title,
                "status": r.status,
                "state_version": r.state_version,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    task = await tasks.get_task(session, task_id)
    return _task_json(task)


@router.post("/tasks/{task_id}/actions/{action}")
async def task_action(
    task_id: uuid.UUID,
    action: str,
    payload: ActionRequest,
    session: SessionDep,
    user: UserDep,
) -> dict:
    trigger = ACTION_TO_TRIGGER.get(action)
    if trigger is None:
        from app.api.deps import ApiError

        raise ApiError(404, "NOT_FOUND", f"unknown action {action!r}")
    task = await tasks.advance(
        session,
        task_id,
        trigger,
        expected_state_version=payload.expected_state_version,
        actor_id=user,
    )
    return _task_json(task)


@router.get("/tasks/{task_id}/plan")
async def get_plan(task_id: uuid.UUID, session: SessionDep, user: UserDep) -> dict:
    row = (
        await session.execute(
            text(
                """
                SELECT v.id, v.version_no, v.status, v.content, v.content_hash
                FROM agent_plans p
                JOIN agent_plan_versions v ON v.id = p.latest_version_id
                WHERE p.task_id = :task
                """
            ),
            {"task": task_id},
        )
    ).first()
    if row is None:
        from app.api.deps import ApiError

        raise ApiError(404, "NOT_FOUND", "task has no plan yet")
    return {
        "plan_version_id": str(row.id),
        "version_no": row.version_no,
        "status": row.status,
        "content": row.content,
        "content_hash": row.content_hash,
        "allowed_triggers": contract.load("plan_version").triggers_from(row.status),
    }
