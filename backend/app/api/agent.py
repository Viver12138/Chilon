"""Agent endpoints.

`POST /tasks/{id}/agent/plan` is **not in D5's 64 endpoints** — the contract has no
"the agent proposes" route, only the teacher's reaction to a plan. Flagged as a gap
here rather than smuggled into an existing action: a planner call is not a teacher
action and must not appear in `allowed_actions`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ApiError, SessionDep, UserDep
from app.services import agent, planner

router = APIRouter(tags=["agent"])


class ProposePlanRequest(BaseModel):
    requirement: str = Field(min_length=1, max_length=2000)
    engine: str | None = Field(
        default=None,
        description="template | deepseek；省略时取 .env 的 CHILON_PLANNER",
    )


@router.post("/tasks/{task_id}/agent/plan")
async def propose_plan(
    task_id: uuid.UUID, payload: ProposePlanRequest, session: SessionDep, user: UserDep
) -> dict:
    try:
        engine = planner.build(payload.engine)
    except planner.PlanGenerationFailed as exc:
        raise ApiError(409, "CAPABILITY_GAP", str(exc)) from exc

    try:
        return await agent.propose_plan(
            session, user, task_id, payload.requirement, plan_engine=engine
        )
    except agent.RequirementIncomplete as exc:
        # the teacher has to say more before anything is planned; nothing was written
        raise ApiError(422, "AST_INVALID", f"需求信息不足：{exc.missing}") from exc
    except planner.PlanGenerationFailed as exc:
        raise ApiError(409, "CAPABILITY_GAP", str(exc)) from exc
