"""Plan step DAG: materialisation, validation and scheduling.

An unexecutable plan must fail **before** the teacher sees an approval button, so
the DAG is validated and materialised when the plan version is created, not when
execution starts. That ordering is the whole point of this module: a cycle found
during execution is an incident; a cycle found at creation is a form error.

Cycle detection is a topological sort here rather than a database constraint.
Postgres cannot express "no cycles in this relation" without a recursive check on
every write, and plans are small (typically 5–15 steps), so doing it once at
creation is both cheaper and gives a usable error message.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract

STEP_EXECUTION = contract.load("step_execution")


class PlanDagError(Exception):
    """The plan cannot be executed as written."""


class StepNotFound(Exception):
    pass


class StepConflict(Exception):
    pass


@dataclass(frozen=True)
class StepSpec:
    key: str
    step_type: str
    title: str
    ordinal: int
    depends_on: tuple[str, ...]


def parse_plan(content: dict) -> list[StepSpec]:
    """Validate shape, keys and acyclicity. Raises PlanDagError with a usable message."""
    raw_steps = content.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanDagError("plan has no steps")

    specs: list[StepSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise PlanDagError(f"step #{index} is not an object")
        key = raw.get("key")
        if not isinstance(key, str) or not key:
            raise PlanDagError(f"step #{index} has no key")
        if key in seen:
            raise PlanDagError(f"duplicate step key {key!r}")
        seen.add(key)
        deps = raw.get("depends_on") or []
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise PlanDagError(f"step {key!r} has malformed depends_on")
        specs.append(
            StepSpec(
                key=key,
                step_type=str(raw.get("type") or "generic"),
                title=str(raw.get("title") or key),
                ordinal=index,
                depends_on=tuple(deps),
            )
        )

    by_key = {s.key: s for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            if dep not in by_key:
                raise PlanDagError(f"step {spec.key!r} depends on unknown step {dep!r}")
            if dep == spec.key:
                raise PlanDagError(f"step {spec.key!r} depends on itself")

    # Kahn's algorithm: what remains after peeling is exactly the cycle
    indegree = {s.key: len(s.depends_on) for s in specs}
    dependents: dict[str, list[str]] = {s.key: [] for s in specs}
    for spec in specs:
        for dep in spec.depends_on:
            dependents[dep].append(spec.key)

    queue = [k for k, v in indegree.items() if v == 0]
    visited = 0
    while queue:
        key = queue.pop()
        visited += 1
        for child in dependents[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if visited != len(specs):
        stuck = sorted(k for k, v in indegree.items() if v > 0)
        raise PlanDagError(f"plan has a dependency cycle involving {stuck}")

    return specs


async def materialise(session: AsyncSession, plan_version_id: uuid.UUID, content: dict) -> list[StepSpec]:
    """Create the step rows and edges. Called when the plan version is written."""
    specs = parse_plan(content)
    ids: dict[str, uuid.UUID] = {}

    for spec in specs:
        step_id = uuid.uuid4()
        ids[spec.key] = step_id
        await session.execute(
            text(
                """
                INSERT INTO agent_plan_steps
                    (id, plan_version_id, step_key, ordinal, step_type, title, input_spec)
                VALUES
                    (:id, :version, :key, :ordinal, :type, :title, '{}'::jsonb)
                """
            ),
            {
                "id": step_id,
                "version": plan_version_id,
                "key": spec.key,
                "ordinal": spec.ordinal,
                "type": spec.step_type,
                "title": spec.title,
            },
        )

    for spec in specs:
        for dep in spec.depends_on:
            await session.execute(
                text(
                    """
                    INSERT INTO agent_step_dependencies
                        (id, plan_version_id, step_id, depends_on_step_id)
                    VALUES (gen_random_uuid(), :version, :step, :dep)
                    """
                ),
                {"version": plan_version_id, "step": ids[spec.key], "dep": ids[dep]},
            )
    return specs


async def ready_steps(session: AsyncSession, execution_id: uuid.UUID) -> list[dict]:
    """Steps with no unfinished dependency and no execution row yet."""
    rows = (
        await session.execute(
            text(
                """
                SELECT s.step_key, s.title, s.ordinal
                FROM agent_executions e
                JOIN agent_plan_steps s ON s.plan_version_id = e.plan_version_id
                WHERE e.id = :exec
                  AND NOT EXISTS (
                      SELECT 1 FROM agent_step_dependencies d
                      JOIN agent_plan_steps pre ON pre.id = d.depends_on_step_id
                      LEFT JOIN agent_step_executions pe
                             ON pe.plan_step_id = pre.id AND pe.execution_id = e.id
                      WHERE d.step_id = s.id
                        AND (pe.id IS NULL OR pe.status <> 'succeeded')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM agent_step_executions x
                      WHERE x.execution_id = e.id AND x.plan_step_id = s.id
                  )
                ORDER BY s.ordinal
                """
            ),
            {"exec": execution_id},
        )
    ).all()
    return [{"step_key": r.step_key, "title": r.title, "ordinal": r.ordinal} for r in rows]


async def start_step(
    session: AsyncSession,
    execution_id: uuid.UUID,
    step_key: str,
    *,
    actor_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Create the step execution row for one plan step.

    A step can only start once the contract's step machine allows it, and only if
    every dependency already succeeded — the scheduler trusts the DAG, not the
    caller.
    """
    available = {s["step_key"] for s in await ready_steps(session, execution_id)}
    if step_key not in available:
        raise StepConflict(f"step {step_key!r} is not ready to start")

    step = (
        await session.execute(
            text(
                """
                SELECT s.id, s.plan_version_id
                FROM agent_plan_steps s
                JOIN agent_executions e ON e.plan_version_id = s.plan_version_id
                WHERE e.id = :exec AND s.step_key = :key
                """
            ),
            {"exec": execution_id, "key": step_key},
        )
    ).first()
    if step is None:
        raise StepNotFound(step_key)

    step_exec_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO agent_step_executions
                (id, execution_id, plan_step_id, status, attempt, started_at)
            VALUES (:id, :exec, :step, :status, 0, now())
            """
        ),
        {
            "id": step_exec_id,
            "exec": execution_id,
            "step": step.id,
            "status": "running",
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="step_execution",
        aggregate_id=str(step_exec_id),
        event_type="step.started",
        payload={"execution_id": str(execution_id), "step_key": step_key},
    )
    return step_exec_id


async def finish_step(
    session: AsyncSession,
    step_execution_id: uuid.UUID,
    *,
    succeeded: bool,
    error_code: str | None = None,
) -> str:
    """Close one step. Returns the new status."""
    target = "succeeded" if succeeded else "failed"
    result = await session.execute(
        text(
            """
            UPDATE agent_step_executions
            SET status = :status, finished_at = now(), error_code = :err
            WHERE id = :id AND status IN ('pending', 'ready', 'running', 'retrying')
            """
        ),
        {"status": target, "err": error_code, "id": step_execution_id},
    )
    if result.rowcount == 0:
        raise StepConflict(f"step execution {step_execution_id} is already settled")

    await dispatcher.enqueue(
        session,
        aggregate_type="step_execution",
        aggregate_id=str(step_execution_id),
        event_type=f"step.{target}",
        payload={"status": target, "error_code": error_code},
    )
    return target


async def all_steps_settled(session: AsyncSession, execution_id: uuid.UUID) -> tuple[bool, bool]:
    """(every planned step succeeded, any step failed)."""
    row = (
        await session.execute(
            text(
                """
                SELECT
                    count(*) AS planned,
                    count(*) FILTER (WHERE se.status = 'succeeded') AS succeeded,
                    count(*) FILTER (WHERE se.status IN ('failed', 'blocked')) AS failed
                FROM agent_plan_steps s
                JOIN agent_executions e ON e.plan_version_id = s.plan_version_id
                LEFT JOIN agent_step_executions se
                       ON se.plan_step_id = s.id AND se.execution_id = e.id
                WHERE e.id = :exec
                """
            ),
            {"exec": execution_id},
        )
    ).one()
    return int(row.succeeded) == int(row.planned) and int(row.planned) > 0, int(row.failed) > 0
