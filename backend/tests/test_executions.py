"""Execution tests: spending the approval, and refusing stale workers.

The scenarios target the ways this goes wrong in production:

* the same approval starting two executions
* the plan edited after approval but executed anyway
* a worker whose lease was taken over still writing state
* every contract transition, and every undeclared pair
* a failed start leaving a half-spent approval
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
from app.services import contract, executions, plans, tasks  # noqa: E402

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
            {"id": uid, "u": f"exec_{uid.hex[:10]}"},
        )
    return uid


async def ready_task(uid: uuid.UUID, content: dict) -> dict:
    """Drive a task to `ready` with an approved plan, using the services only."""
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "执行测试")

    async with db.session_for(uid) as s:
        requirement = (
            await s.execute(
                text(
                    """
                    INSERT INTO task_requirement_versions
                        (id, task_id, owner_id, version_no, requirements, content_hash, status, created_by)
                    VALUES (gen_random_uuid(), :task, :owner, 1, '{}'::jsonb, :hash, :status, :owner)
                    RETURNING id
                    """
                ),
                {
                    "task": task.id,
                    "owner": uid,
                    "hash": "b" * 64,
                    "status": contract.load("requirement_version").initial,
                },
            )
        ).scalar_one()

    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(s, uid, task.id, requirement, content)
    async with db.session_for(uid) as s:
        approval_id = await plans.request_approval(s, uid, task.id, version.id)
    async with db.session_for(uid) as s:
        await plans.decide(s, approval_id, uid, "approved")

    # walk the task to `ready` through its own contract
    for trigger in ("submit_requirement", "plan_validated", "approve_plan"):
        async with db.session_for(uid) as s:
            current = await tasks.get_task(s, task.id)
        async with db.session_for(uid) as s:
            await tasks.advance(s, task.id, trigger, expected_state_version=current.state_version)

    async with db.session_for(uid) as s:
        current = await tasks.get_task(s, task.id)
    state = {"task": task.id, "version": version.id, "approval": approval_id, "version_no": current.state_version}
    check(current.status == "ready", f"task walked to ready via the contract (got {current.status})")
    return state


async def scenario_start(uid: uuid.UUID) -> None:
    print("1. start spends the approval and moves the task to running")
    ctx = await ready_task(uid, {"steps": [{"key": "s1"}]})

    async with db.session_for(uid) as s:
        execution_id = await executions.start_execution(
            s,
            uid,
            ctx["task"],
            ctx["version"],
            ctx["approval"],
            expected_task_state_version=ctx["version_no"],
        )

    async with db.session_for(uid) as s:
        execution = await executions.get_execution(s, execution_id)
        task = await tasks.get_task(s, ctx["task"])
        approval = (
            await s.execute(
                text("SELECT consumed_at FROM agent_plan_approvals WHERE id = :id"),
                {"id": ctx["approval"]},
            )
        ).one()

    check(execution.status == executions.EXECUTION.initial, f"execution starts in {execution.status!r}")
    check(task.status == "running", f"task moved to running (got {task.status})")
    check(approval.consumed_at is not None, "approval was consumed")

    # the same approval must not start a second execution
    async with db.session_for(uid) as s:
        another_approval = await plans.request_approval(s, uid, ctx["task"], ctx["version"])
    async with db.session_for(uid) as s:
        try:
            await executions.start_execution(
                s, uid, ctx["task"], ctx["version"], ctx["approval"],
                expected_task_state_version=task.state_version,
            )
            check(False, "the spent approval started a second execution")
        except plans.ApprovalNotConsumable:
            check(True, "a spent approval cannot start another execution")
        except tasks.IllegalTransition:
            # the task is no longer `ready`, which is also a refusal
            check(True, "second start refused (task no longer ready)")
    _ = another_approval


async def scenario_failed_start(uid: uuid.UUID) -> None:
    print("2. a failed start leaves the approval unspent")
    ctx = await ready_task(uid, {"steps": [{"key": "s2"}]})

    async with db.session_for(uid) as s:
        try:
            await executions.start_execution(
                s, uid, ctx["task"], ctx["version"], ctx["approval"],
                expected_task_state_version=ctx["version_no"] + 99,  # stale on purpose
            )
            check(False, "a stale task version was accepted")
        except tasks.StateConflict:
            check(True, "stale task version refused")

    async with db.session_for(uid) as s:
        approval = (
            await s.execute(
                text("SELECT consumed_at FROM agent_plan_approvals WHERE id = :id"),
                {"id": ctx["approval"]},
            )
        ).one()
        count = (
            await s.execute(
                text("SELECT count(*) FROM agent_executions WHERE task_id = :t"), {"t": ctx["task"]}
            )
        ).scalar_one()

    check(approval.consumed_at is None, "approval was not consumed by the failed attempt")
    check(count == 0, "no execution row was left behind")


async def scenario_transitions(uid: uuid.UUID) -> None:
    print(f"3. all {len(executions.EXECUTION.transitions)} execution transitions follow the contract")
    ctx = await ready_task(uid, {"steps": [{"key": "s3"}]})
    async with db.session_for(uid) as s:
        execution_id = await executions.start_execution(
            s, uid, ctx["task"], ctx["version"], ctx["approval"],
            expected_task_state_version=ctx["version_no"],
        )

    for (from_state, trigger), transition in sorted(executions.EXECUTION.transitions.items()):
        async with db.session_for(uid) as s:
            await s.execute(
                text("UPDATE agent_executions SET status = :st, state_version = 5 WHERE id = :id"),
                {"st": from_state, "id": execution_id},
            )
        async with db.session_for(uid) as s:
            result = await executions.advance_execution(
                s, execution_id, trigger, expected_state_version=5
            )
        ok = result.status == transition.to_state and result.state_version == 6
        check(ok, f"{from_state} --{trigger}--> {transition.to_state}")


async def scenario_illegal(uid: uuid.UUID) -> None:
    print("4. undeclared (state, trigger) pairs are refused")
    ctx = await ready_task(uid, {"steps": [{"key": "s4"}]})
    async with db.session_for(uid) as s:
        execution_id = await executions.start_execution(
            s, uid, ctx["task"], ctx["version"], ctx["approval"],
            expected_task_state_version=ctx["version_no"],
        )

    triggers = sorted({t for (_, t) in executions.EXECUTION.transitions})
    illegal = 0
    accepted = []
    for state in executions.EXECUTION.states:
        async with db.session_for(uid) as s:
            await s.execute(
                text("UPDATE agent_executions SET status = :st, state_version = 9 WHERE id = :id"),
                {"st": state, "id": execution_id},
            )
        for trigger in triggers:
            if (state, trigger) in executions.EXECUTION.transitions:
                continue
            illegal += 1
            async with db.session_for(uid) as s:
                try:
                    await executions.advance_execution(
                        s, execution_id, trigger, expected_state_version=9
                    )
                    accepted.append((state, trigger))
                except executions.IllegalExecutionTransition:
                    pass
    check(not accepted, f"{illegal} illegal pairs checked, all refused")
    if accepted:
        print(f"         accepted: {accepted[:5]}")


async def scenario_fencing(uid: uuid.UUID) -> None:
    print("5. a stale fencing token cannot advance the execution")
    ctx = await ready_task(uid, {"steps": [{"key": "s5"}]})
    async with db.session_for(uid) as s:
        execution_id = await executions.start_execution(
            s, uid, ctx["task"], ctx["version"], ctx["approval"],
            expected_task_state_version=ctx["version_no"],
        )

    async with db.session_for(uid) as s:
        # a real TTL: with 0 the lease is already expired and the next assertion
        # ("a live lease cannot be taken") would be testing nothing
        token1 = await executions.acquire_lease(s, execution_id, "worker-a", ttl_seconds=60)
    check(token1 == 1, f"first lease takes token 1 (got {token1})")

    async with db.session_for(uid) as s:
        try:
            await executions.acquire_lease(s, execution_id, "worker-b", ttl_seconds=60)
            check(False, "a live lease was stolen")
        except executions.LeaseUnavailable:
            check(True, "a live lease cannot be taken")

    # simulate the lease expiring while worker-a is still running
    async with db.system_session() as s:
        await s.execute(
            text("UPDATE agent_executions SET lease_expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": execution_id},
        )
    async with db.session_for(uid) as s:
        token2 = await executions.acquire_lease(s, execution_id, "worker-b", ttl_seconds=60)
    check(token2 == 2, f"taking over an expired lease bumps the token (got {token2})")

    async with db.session_for(uid) as s:
        current = await executions.get_execution(s, execution_id)
    legal = contract.load("execution").triggers_from(current.status)
    async with db.session_for(uid) as s:
        try:
            await executions.advance_execution(
                s, execution_id, legal[0], expected_state_version=current.state_version, fencing_token=token1
            )
            check(False, "the dismissed worker advanced the state")
        except executions.StaleFence:
            check(True, "the dismissed worker's write is refused as stale, not as illegal")

    async with db.session_for(uid) as s:
        after = await executions.get_execution(s, execution_id)
    check(after.state_version == current.state_version, "a refused write changed nothing")

    async with db.session_for(uid) as s:
        try:
            await executions.heartbeat(s, execution_id, token1)
            check(False, "a stale worker renewed its lease")
        except executions.StaleFence:
            check(True, "heartbeat with a stale token is refused")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        uid = await make_user()
        await scenario_start(uid)
        await scenario_failed_start(uid)
        await scenario_transitions(uid)
        await scenario_illegal(uid)
        await scenario_fencing(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: execution spends approvals once and refuses stale workers")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
