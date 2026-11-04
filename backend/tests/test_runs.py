"""Run mapping and outcome reconciliation tests.

The important assertion is negative: reconciling an unknown outcome must never
create a second tool invocation. A timeout that secretly retried would be the worst
possible behaviour — it turns "we don't know" into "we might have done it twice".
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import contract, executions, plans, runs, tasks, tools  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def make_user() -> uuid.UUID:
    uid = uuid.uuid4()
    async with db.session_for(uid) as s:
        await s.execute(
            text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
            {"id": uid, "u": f"run_{uid.hex[:10]}"},
        )
    return uid


async def running_execution(uid: uuid.UUID) -> uuid.UUID:
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "运行测试")
    async with db.session_for(uid) as s:
        requirement = (
            await s.execute(
                text(
                    """
                    INSERT INTO task_requirement_versions
                        (id, task_id, owner_id, version_no, requirements, content_hash, status, created_by)
                    VALUES (gen_random_uuid(), :t, :o, 1, '{}'::jsonb, :h, :st, :o)
                    RETURNING id
                    """
                ),
                {"t": task.id, "o": uid, "h": "f" * 64,
                 "st": contract.load("requirement_version").initial},
            )
        ).scalar_one()
    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(
            s, uid, task.id, requirement, {"steps": [{"key": "s1"}]}
        )
    async with db.session_for(uid) as s:
        approval = await plans.request_approval(s, uid, task.id, version.id)
    async with db.session_for(uid) as s:
        await plans.decide(s, approval, uid, "approved")
    for trigger in ("submit_requirement", "plan_validated", "approve_plan"):
        async with db.session_for(uid) as s:
            current = await tasks.get_task(s, task.id)
        async with db.session_for(uid) as s:
            await tasks.advance(s, task.id, trigger, expected_state_version=current.state_version)
    async with db.session_for(uid) as s:
        current = await tasks.get_task(s, task.id)
    async with db.session_for(uid) as s:
        return await executions.start_execution(
            s, uid, task.id, version.id, approval,
            expected_task_state_version=current.state_version,
        )


async def granted_tool(uid: uuid.UUID) -> str:
    key = f"test.rec_{uuid.uuid4().hex[:6]}"
    tool_id = uuid.uuid4()
    async with db.session_for(uid) as s:
        await s.execute(
            text(
                """
                INSERT INTO agent_tool_definitions
                    (id, key, version, name, side_effect_level)
                VALUES (:id, :key, '1.0.0', :key, 'write')
                """
            ),
            {"id": tool_id, "key": key},
        )
        await s.execute(
            text(
                """
                INSERT INTO agent_tool_grants (id, owner_id, tool_definition_id, capability)
                VALUES (gen_random_uuid(), :o, :t, 'invoke')
                """
            ),
            {"o": uid, "t": tool_id},
        )
    return key


async def invocation_count(key: str) -> int:
    async with db.system_session() as s:
        return (
            await s.execute(
                text(
                    """
                    SELECT count(*) FROM agent_tool_executions e
                    JOIN agent_tool_definitions d ON d.id = e.tool_definition_id
                    WHERE d.key = :k
                    """
                ),
                {"k": key},
            )
        ).scalar_one()


async def scenario_run(uid: uuid.UUID) -> None:
    print("1. runs map sessions to an execution, with monotonic runtime events")
    execution_id = await running_execution(uid)

    async with db.session_for(uid) as s:
        first = await runs.start_run(s, execution_id, model="deepseek", harness_session_id="sess-1")
    check(first.ordinal == 1, f"first run is ordinal 1 (got {first.ordinal})")
    check(first.status == runs.RUN.initial, f"run starts in {first.status!r}")

    async with db.session_for(uid) as s:
        second = await runs.start_run(s, execution_id, model="deepseek")
    check(second.ordinal == 2, f"second run increments (got {second.ordinal})")

    async with db.session_for(uid) as s:
        s1 = await runs.record_runtime_event(s, first.id, "assistant_message", {"text": "hi"})
        s2 = await runs.record_runtime_event(s, first.id, "tool_call", {"tool": "x"})
    check((s1, s2) == (1, 2), f"runtime event seq is monotonic per run (got {s1}, {s2})")

    async with db.session_for(uid) as s:
        status = await runs.advance_run(s, first.id, "session_ready")
    check(status == "running", f"run advances on its contract (got {status})")

    async with db.session_for(uid) as s:
        try:
            await runs.advance_run(s, first.id, "session_ready")
            check(False, "an illegal run transition was accepted")
        except runs.IllegalRunTransition:
            check(True, "an illegal run transition is refused")

    async with db.session_for(uid) as s:
        hashes = (
            await s.execute(
                text("SELECT count(*) FROM agent_runtime_events WHERE payload_hash IS NOT NULL")
            )
        ).scalar_one()
    check(hashes >= 2, "runtime events carry payload hashes")


async def scenario_unknown(uid: uuid.UUID) -> None:
    print("2. a timeout becomes 'unknown', not 'failed'")
    execution_id = await running_execution(uid)
    key = await granted_tool(uid)

    async with db.session_for(uid) as s:
        inv = await tools.invoke(s, execution_id, key, {"n": 1})
    for trigger in ("begin_authorization", "authorize", "dispatch", "tool_running"):
        async with db.session_for(uid) as s:
            await tools.advance(s, inv.id, trigger)

    async with db.session_for(uid) as s:
        status = await runs.mark_tool_outcome_unknown(s, inv.id)
    check(status == "outcome_unknown", f"timeout recorded as unknown (got {status})")

    async with db.session_for(uid) as s:
        row = (
            await s.execute(
                text("SELECT status, error_code FROM agent_tool_executions WHERE id = :id"),
                {"id": inv.id},
            )
        ).one()
    check(row.status == "outcome_unknown", "the row says unknown, not failed")


async def scenario_reconcile(uid: uuid.UUID) -> None:
    print("3. reconciliation applies an observed outcome and never re-invokes")
    execution_id = await running_execution(uid)

    # -- observed as succeeded
    key_ok = await granted_tool(uid)
    async with db.session_for(uid) as s:
        inv = await tools.invoke(s, execution_id, key_ok, {"n": 2})
    for trigger in ("begin_authorization", "authorize", "dispatch", "tool_running"):
        async with db.session_for(uid) as s:
            await tools.advance(s, inv.id, trigger)
    async with db.session_for(uid) as s:
        await runs.mark_tool_outcome_unknown(s, inv.id)

    async with db.session_for(uid) as s:
        status = await runs.reconcile_tool(
            s, inv.id, observed_status="succeeded", observed_result={"bytes": 42}
        )
    check(status == "succeeded", f"observed success is recorded (got {status})")
    check(await invocation_count(key_ok) == 1, "reconciliation did not create a second invocation")

    async with db.session_for(uid) as s:
        row = (
            await s.execute(
                text("SELECT status, result_hash FROM agent_tool_executions WHERE id = :id"),
                {"id": inv.id},
            )
        ).one()
    check(row.status == "succeeded" and row.result_hash is not None, "result and hash stored")

    # -- reconciling again is idempotent, not a second settle
    async with db.session_for(uid) as s:
        again = await runs.reconcile_tool(s, inv.id, observed_status="failed")
    check(again == "succeeded", "a settled invocation is not re-settled by a later reconcile")

    # -- observed as failed
    key_bad = await granted_tool(uid)
    async with db.session_for(uid) as s:
        inv2 = await tools.invoke(s, execution_id, key_bad, {"n": 3})
    for trigger in ("begin_authorization", "authorize", "dispatch", "tool_running"):
        async with db.session_for(uid) as s:
            await tools.advance(s, inv2.id, trigger)
    async with db.session_for(uid) as s:
        await runs.mark_tool_outcome_unknown(s, inv2.id)
    async with db.session_for(uid) as s:
        status2 = await runs.reconcile_tool(
            s, inv2.id, observed_status="failed", error_code="DOWNSTREAM_500"
        )
    check(status2 == "failed", f"observed failure is recorded (got {status2})")

    # -- still unknown stays unknown, and stays single
    key_unknown = await granted_tool(uid)
    async with db.session_for(uid) as s:
        inv3 = await tools.invoke(s, execution_id, key_unknown, {"n": 4})
    for trigger in ("begin_authorization", "authorize", "dispatch", "tool_running"):
        async with db.session_for(uid) as s:
            await tools.advance(s, inv3.id, trigger)
    async with db.session_for(uid) as s:
        await runs.mark_tool_outcome_unknown(s, inv3.id)
    async with db.session_for(uid) as s:
        status3 = await runs.reconcile_tool(s, inv3.id, observed_status="unknown")
    check(status3 == "outcome_unknown", f"still-unknown stays unknown (got {status3})")
    check(
        await invocation_count(key_unknown) == 1,
        "an unresolved unknown is not retried into a duplicate side effect",
    )


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)  # TODO: seeding needs an owner context; see D.50
    try:
        uid = await make_user()
        await scenario_run(uid)
        await scenario_unknown(uid)
        await scenario_reconcile(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: runs are mapped, and unknown outcomes are reconciled without retrying")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
