"""Executor: run an execution's ready steps by calling their tools.

One call processes as many ready steps as it can, then settles the execution. The
loop is deliberately simple, but three properties matter and are tested:

* a step only starts when its dependencies succeeded (the DAG decides, not the loop);
* every tool call goes through `tools.invoke`, so retries are idempotent and granted
  tools are enforced;
* a failure stops that branch and leaves the execution in `needs_attention` rather
  than pretending the run finished.

This runs inside the caller's transaction. For a real worker each step should be its
own transaction with a lease and fencing token — the primitives exist
(`executions.acquire_lease`), and the split is a deployment concern, not a modelling one.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import executions, steps, tools
from app.tools import impl as tool_impl


class ExecutionNotRunnable(Exception):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()




async def publish_progress(
    session: AsyncSession,
    execution_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Mirror a step event into the task's conversation stream, if it has one.

    The stream is the teacher's view of what is happening. Writing it in the same
    transaction as the step keeps the two from disagreeing: a step that committed
    always has its event, and an event never describes a step that rolled back.
    """
    from app.services import event_stream

    conversation_id = (
        await session.execute(
            text(
                """
                SELECT c.id
                FROM conversations c
                JOIN tasks t ON t.id = c.task_id
                JOIN agent_executions e ON e.task_id = t.id
                WHERE e.id = :exec
                ORDER BY c.created_at
                LIMIT 1
                """
            ),
            {"exec": execution_id},
        )
    ).scalar()
    if conversation_id is None:
        return
    await event_stream.append_event(
        session, conversation_id, event_type, payload, aggregate="execution", aggregate_id=execution_id
    )

async def _plan_context(session: AsyncSession, execution_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT v.content AS plan_content, r.requirements AS requirement
                FROM agent_executions e
                JOIN agent_plan_versions v ON v.id = e.plan_version_id
                LEFT JOIN task_requirement_versions r
                       ON r.id = v.requirement_version_id
                WHERE e.id = :exec
                """
            ),
            {"exec": execution_id},
        )
    ).first()
    if row is None:
        raise ExecutionNotRunnable(f"execution {execution_id} has no plan")
    return {"plan": row.plan_content, "requirement": row.requirement or {}}


async def _dependency_outputs(session: AsyncSession, execution_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                """
                SELECT s.step_key, se.output
                FROM agent_step_executions se
                JOIN agent_plan_steps s ON s.id = se.plan_step_id
                WHERE se.execution_id = :exec AND se.output IS NOT NULL
                """
            ),
            {"exec": execution_id},
        )
    ).all()
    return {r.step_key: r.output for r in rows}


def _ancestors(spec_by_key: dict[str, Any], key: str) -> set[str]:
    """Every step this one transitively depends on.

    Only direct parents would be wrong: a check step depends on the generate steps
    and, through them, on retrieval — and it needs the retrieval result to resolve
    citations. Unrelated branches stay invisible, so steps are still isolated.
    """
    seen: set[str] = set()
    stack = list((spec_by_key.get(key, {}).get("depends_on") or []))
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        stack.extend(spec_by_key.get(dep, {}).get("depends_on") or [])
    return seen


async def run_once(
    session: AsyncSession,
    owner_id: uuid.UUID,
    execution_id: uuid.UUID,
    *,
    max_rounds: int = 6,
) -> dict[str, Any]:
    """Process ready steps until nothing is runnable, then settle the execution."""
    execution = await executions.get_execution(session, execution_id)

    # A worker polls everything it finds, including executions another worker already
    # settled. Re-running a finished execution is a no-op, not an error — raising here
    # would turn normal polling into noise in the logs.
    if execution.status in ("succeeded", "failed", "cancelled", "superseded", "expired"):
        return {
            "execution_id": str(execution_id),
            "processed": [],
            "failed_steps": [],
            "outcome": execution.status,
            "note": "already settled",
        }

    if execution.status not in ("queued", "starting", "running", "pause_requested"):
        raise ExecutionNotRunnable(
            f"execution is {execution.status!r}, which does not accept step work"
        )

    # A worker has to bring the execution up before doing step work: queued is not a
    # state the step machine or the terminal transitions accept.
    if execution.status == "queued":
        if executions.EXECUTION.trigger_for("queued", "acquire_lease"):
            await executions.advance_execution(
                session, execution_id, "acquire_lease", expected_state_version=execution.state_version
            )
            execution = await executions.get_execution(session, execution_id)
    if execution.status == "starting":
        if executions.EXECUTION.trigger_for("starting", "runtime_started"):
            await executions.advance_execution(
                session, execution_id, "runtime_started", expected_state_version=execution.state_version
            )
            execution = await executions.get_execution(session, execution_id)

    context = await _plan_context(session, execution_id)
    spec_by_key = {s["key"]: s for s in context["plan"].get("steps", [])}

    processed: list[dict[str, Any]] = []
    failed_keys: list[str] = []

    for _ in range(max_rounds):
        ready = await steps.ready_steps(session, execution_id)
        if not ready:
            break
        for item in ready:
            key = item["step_key"]
            spec = spec_by_key.get(key)
            if spec is None:
                failed_keys.append(key)
                continue

            step_exec_id = await steps.start_step(session, execution_id, key, actor_id=owner_id)

            deps_outputs = await _dependency_outputs(session, execution_id)
            upstream = _ancestors(spec_by_key, key)
            branch = {d: deps_outputs[d] for d in upstream if d in deps_outputs}

            ctx = tool_impl.ToolContext(
                owner_id=owner_id,
                execution_id=execution_id,
                step_key=key,
                spec=spec,
                requirement=context["requirement"],
                deps=branch,
            )

            tool_key = spec.get("type", "")
            implementation = tool_impl.TOOLS.get(tool_key)
            if implementation is None:
                await steps.finish_step(
                    session, step_exec_id, succeeded=False, error_code="TOOL_NOT_IMPLEMENTED"
                )
                failed_keys.append(key)
                continue

            # record the intent first: the row exists even if the call dies mid-flight
            invocation = await tools.invoke(
                session,
                execution_id,
                tool_key,
                {"step": key, "requirement_hash": _hash(context["requirement"]), "spec": spec},
                step_execution_id=step_exec_id,
                actor_id=owner_id,
            )

            try:
                output = await implementation(session, ctx)
            except Exception as exc:  # noqa: BLE001 - any tool failure stops the branch
                await tools.record_result(
                    session,
                    invocation.id,
                    None,
                    succeeded=False,
                    error_code=type(exc).__name__,
                )
                await steps.finish_step(
                    session, step_exec_id, succeeded=False, error_code=type(exc).__name__
                )
                failed_keys.append(key)
                continue

            await session.execute(
                text(
                    """
                    UPDATE agent_step_executions
                    SET output = CAST(:output AS jsonb)
                    WHERE id = :id
                    """
                ),
                {"output": json.dumps(output, ensure_ascii=False), "id": step_exec_id},
            )
            await tools.record_result(session, invocation.id, output, succeeded=True)
            await steps.finish_step(session, step_exec_id, succeeded=True)
            await publish_progress(
                session,
                execution_id,
                "execution.progress",
                {"step": key, "tool": tool_key, "status": "succeeded"},
            )

            reason = "replayed" if invocation.replayed else "executed"
            processed.append({"step_key": key, "tool": tool_key, "result": reason})

    done, any_failed = await steps.all_steps_settled(session, execution_id)

    if done:
        current = await executions.get_execution(session, execution_id)
        if executions.EXECUTION.trigger_for(current.status, "steps_succeeded"):
            await executions.advance_execution(
                session, execution_id, "steps_succeeded", expected_state_version=current.state_version
            )
            outcome = "succeeded"
        else:
            outcome = current.status
    elif any_failed or failed_keys:
        current = await executions.get_execution(session, execution_id)
        if executions.EXECUTION.trigger_for(current.status, "unrecoverable_failure"):
            await executions.advance_execution(
                session,
                execution_id,
                "unrecoverable_failure",
                expected_state_version=current.state_version,
            )
            outcome = "failed"
        else:
            outcome = current.status
        await dispatcher.enqueue(
            session,
            aggregate_type="execution",
            aggregate_id=str(execution_id),
            event_type="execution.steps_failed",
            payload={"failed_steps": failed_keys},
        )
    else:
        outcome = "in_progress"

    return {
        "execution_id": str(execution_id),
        "processed": processed,
        "failed_steps": failed_keys,
        "outcome": outcome,
    }
