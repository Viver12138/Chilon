"""The agent turn: requirement in, approvable plan out.

This is what was missing — before it, a plan could only be created by test code
calling the service directly. Now there is a single entry point that does the whole
turn:

    extract requirement -> record it -> plan -> validate -> persist -> ask for approval

Every step that can fail does so *before* anything is committed, and the task is
left in a state that says what happened (`needs_attention`), never in a half-planned
state that looks healthy.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract, plans, planner, steps, tasks

SOURCE_KEYWORDS = {
    "textbook": ("教材", "课本", "人教版", "教科书"),
    "workbook": ("教辅", "练习册", "辅导书", "同步练习"),
    "gaokao_paper": ("高考题", "高考真题", "真题"),
    "mock_exam": ("模拟题", "模拟卷", "模考", "联考"),
}


class RequirementIncomplete(Exception):
    """Required information is missing. The task stays `draft`; nothing is planned."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"requirement is missing: {missing}")


@dataclass
class Requirement:
    topic: str
    sources: list[str] = field(default_factory=list)
    question_count: int | None = None
    raw_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "sources": self.sources,
            "question_count": self.question_count,
            "raw_text": self.raw_text,
        }


def extract_requirement(text: str) -> Requirement:
    """Deterministic extraction.

    Deliberately conservative: it never invents a value. If the teacher did not say
    how many questions, `question_count` stays None and the planner decides a
    default — that is a planning choice, not a fact this function is allowed to make up.
    """
    if not text or not text.strip():
        raise RequirementIncomplete(["需求描述"])

    lowered = text.lower()
    sources = [
        key for key, words in SOURCE_KEYWORDS.items() if any(w in lowered for w in words)
    ]

    match = re.search(r"(\d+)\s*(?:道|个|题)", text)
    count = int(match.group(1)) if match else None

    topic = text.strip()
    for prefix in ("出一份", "出", "生成", "帮我", "请"):
        if topic.startswith(prefix):
            topic = topic[len(prefix) :]
    topic = re.sub(r"\d+\s*(?:道|个)题?", "", topic).strip(" ，,。")
    if not topic:
        raise RequirementIncomplete(["课题"])

    if not sources:
        # the platform knowledge base is the default source family (§1.6.1), so an
        # unspecified source is a default, not a missing value
        sources = []

    return Requirement(topic=topic, sources=sources, question_count=count, raw_text=text)


async def available_tools(session: AsyncSession, owner_id: uuid.UUID) -> list[planner.ToolSpec]:
    """Tools this teacher may actually use: enabled and granted."""
    rows = (
        await session.execute(
            text(
                """
                SELECT d.key, d.name, d.side_effect_level
                FROM agent_tool_definitions d
                JOIN agent_tool_grants g ON g.tool_definition_id = d.id
                WHERE d.is_enabled AND g.owner_id = :owner AND g.revoked_at IS NULL
                ORDER BY d.key
                """
            ),
            {"owner": owner_id},
        )
    ).all()
    return [planner.ToolSpec(r.key, r.name, r.side_effect_level) for r in rows]


async def propose_plan(
    session: AsyncSession,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    requirement_text: str,
    *,
    plan_engine: planner.Planner | None = None,
) -> dict[str, Any]:
    """Run one agent turn. Raises RequirementIncomplete before touching the database."""
    requirement = extract_requirement(requirement_text)
    engine = plan_engine or planner.build()

    task = await tasks.get_task(session, task_id)
    transition = tasks.TASK.trigger_for(task.status, "submit_requirement")
    if transition is None:
        raise tasks.IllegalTransition(
            task.status, "submit_requirement", tasks.allowed_triggers(task.status)
        )

    requirement_version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO task_requirement_versions
                (id, task_id, owner_id, version_no, requirements, content_hash, status, created_by)
            VALUES (:id, :task, :owner, 1, CAST(:req AS jsonb), :hash, :status, :owner)
            """
        ),
        {
            "id": requirement_version_id,
            "task": task_id,
            "owner": owner_id,
            "req": _json(requirement.as_dict()),
            "hash": _sha(_json(requirement.as_dict())),
            "status": contract.load("requirement_version").initial,
        },
    )
    await tasks.advance(
        session, task_id, "submit_requirement", expected_state_version=task.state_version
    )

    tools = await available_tools(session, owner_id)
    if not tools:
        raise planner.PlanGenerationFailed("no tools are granted to this teacher")

    content = await engine.plan(requirement.as_dict(), tools)
    specs = planner.validate_plan(content, {t.key for t in tools})

    version = await plans.create_plan_version(
        session, owner_id, task_id, requirement_version_id, content
    )
    approval_id = await plans.request_approval(session, owner_id, task_id, version.id)

    current = await tasks.get_task(session, task_id)
    if tasks.TASK.trigger_for(current.status, "plan_validated"):
        await tasks.advance(
            session,
            task_id,
            "plan_validated",
            expected_state_version=current.state_version,
        )

    await dispatcher.enqueue(
        session,
        aggregate_type="task",
        aggregate_id=str(task_id),
        event_type="agent.plan_proposed",
        payload={
            "task_id": str(task_id),
            "plan_version_id": str(version.id),
            "approval_id": str(approval_id),
            "steps": len(specs),
            "requirement_version_id": str(requirement_version_id),
        },
    )

    return {
        "requirement": requirement.as_dict(),
        "requirement_version_id": str(requirement_version_id),
        "plan_version_id": str(version.id),
        "approval_id": str(approval_id),
        "content_hash": version.content_hash,
        "steps": [
            {"key": s.key, "type": s.step_type, "title": s.title, "depends_on": list(s.depends_on)}
            for s in specs
        ],
    }


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# `steps` is imported for its StepSpec type used in annotations above
_ = steps
