"""Agent runs and outcome reconciliation.

Two things live here because they are the same problem seen from both ends:
what the runtime actually did (`agent_runs`, `agent_runtime_events`), and what we
do when we do not know whether a tool call happened.

**The rule for unknown outcomes (master §15.3):** a timeout is not a failure. The
only safe move is to ask the outside world what its state is and record that. This
module therefore never re-invokes a tool during reconciliation — it accepts an
observed outcome. A reconciliation function that retries would turn an unknown
outcome into a possible duplicate side effect, which is worse than not knowing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import contract, tools

RUN = contract.load("agent_run")


class RunError(Exception):
    """Base class for run errors."""


class RunNotFound(RunError):
    pass


class IllegalRunTransition(RunError):
    pass


class ReconciliationError(Exception):
    """The observed outcome cannot be applied to this invocation."""


@dataclass(frozen=True)
class Run:
    id: uuid.UUID
    execution_id: uuid.UUID
    ordinal: int
    status: str
    harness_session_id: str | None


async def start_run(
    session: AsyncSession,
    execution_id: uuid.UUID,
    *,
    model: str | None = None,
    prompt_version: str | None = None,
    harness_session_id: str | None = None,
) -> Run:
    ordinal = (
        await session.execute(
            text("SELECT COALESCE(max(ordinal), 0) + 1 FROM agent_runs WHERE execution_id = :e"),
            {"e": execution_id},
        )
    ).scalar_one()

    run_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO agent_runs
                (id, execution_id, ordinal, harness_session_id, model, prompt_version, status)
            VALUES (:id, :exec, :ordinal, :session, :model, :prompt, :status)
            """
        ),
        {
            "id": run_id,
            "exec": execution_id,
            "ordinal": ordinal,
            "session": harness_session_id,
            "model": model,
            "prompt": prompt_version,
            "status": RUN.initial,
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="agent_run",
        aggregate_id=str(run_id),
        event_type="run.started",
        payload={"execution_id": str(execution_id), "ordinal": ordinal},
    )
    return Run(run_id, execution_id, ordinal, RUN.initial, harness_session_id)


async def advance_run(session: AsyncSession, run_id: uuid.UUID, trigger: str) -> str:
    current = (
        await session.execute(text("SELECT status FROM agent_runs WHERE id = :id"), {"id": run_id})
    ).scalar()
    if current is None:
        raise RunNotFound(str(run_id))

    transition = RUN.trigger_for(current, trigger)
    if transition is None:
        raise IllegalRunTransition(f"trigger {trigger!r} is not legal in run state {current!r}")

    await session.execute(
        text("UPDATE agent_runs SET status = :status WHERE id = :id AND status = :current"),
        {"status": transition.to_state, "id": run_id, "current": current},
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="agent_run",
        aggregate_id=str(run_id),
        event_type="run.status_changed",
        payload={"from": current, "to": transition.to_state, "trigger": trigger},
    )
    return transition.to_state


async def record_runtime_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> int:
    """Append one raw runtime event. Sequence numbers are per run and monotonic."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    seq = (
        await session.execute(
            text("SELECT COALESCE(max(seq), 0) + 1 FROM agent_runtime_events WHERE agent_run_id = :r"),
            {"r": run_id},
        )
    ).scalar_one()

    await session.execute(
        text(
            """
            INSERT INTO agent_runtime_events
                (id, agent_run_id, seq, event_type, payload, payload_hash, occurred_at)
            VALUES (gen_random_uuid(), :run, :seq, :type, CAST(:payload AS jsonb), :hash, now())
            """
        ),
        {
            "run": run_id,
            "seq": seq,
            "type": event_type,
            "payload": body,
            "hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        },
    )
    return seq


async def mark_tool_outcome_unknown(session: AsyncSession, invocation_id: uuid.UUID) -> str:
    """Timeout: record that we do not know, and say so explicitly."""
    return await tools.advance(session, invocation_id, "tool_timeout")


async def reconcile_tool(
    session: AsyncSession,
    invocation_id: uuid.UUID,
    *,
    observed_status: str,
    observed_result: dict | None = None,
    error_code: str | None = None,
) -> str:
    """Apply an externally observed outcome. Never re-invokes the tool.

    `observed_status` is what the outside world reports: 'succeeded', 'failed' or
    'unknown'. Anything else is a bug in the caller, not a state we guess at.
    """
    current = (
        await session.execute(
            text("SELECT status FROM agent_tool_executions WHERE id = :id"), {"id": invocation_id}
        )
    ).scalar()
    if current is None:
        raise ReconciliationError(f"invocation {invocation_id} not found")

    if current == "succeeded" or current == "failed":
        # already settled: reconciliation is idempotent, not a second settle
        return current

    if observed_status == "succeeded":
        # the tool ran; move it through the contract to `running`, then record
        if current == "outcome_unknown":
            await session.execute(
                text("UPDATE agent_tool_executions SET status = 'running' WHERE id = :id"),
                {"id": invocation_id},
            )
        await tools.record_result(session, invocation_id, observed_result, succeeded=True)
        return "succeeded"

    if observed_status == "failed":
        if current == "outcome_unknown":
            await session.execute(
                text("UPDATE agent_tool_executions SET status = 'running' WHERE id = :id"),
                {"id": invocation_id},
            )
        await tools.record_result(
            session, invocation_id, observed_result, succeeded=False, error_code=error_code
        )
        return "failed"

    if observed_status == "unknown":
        # still unknown: leave it alone so an operator sees it. Retrying here is
        # exactly the mistake this table exists to prevent.
        if current != "outcome_unknown":
            await tools.advance(session, invocation_id, "tool_timeout")
        return "outcome_unknown"

    raise ReconciliationError(f"unknown observed_status {observed_status!r}")
