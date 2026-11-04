"""Step DAG tests: validate at creation, schedule at execution.

The failure these guard against is ordering: a plan whose graph cannot run must be
rejected while the teacher is still writing it, not after they approved it.
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
from tests.support import provision_runtime_role  # noqa: E402
from app.services import contract, executions, plans, steps, tasks  # noqa: E402

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
            {"id": uid, "u": f"dag_{uid.hex[:10]}"},
        )
    return uid


async def ready_task(uid: uuid.UUID, content: dict) -> dict:
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "DAG 测试")
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
                    "hash": "c" * 64,
                    "status": contract.load("requirement_version").initial,
                },
            )
        ).scalar_one()
    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(s, uid, task.id, requirement, content)
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
        execution_id = await executions.start_execution(
            s, uid, task.id, version.id, approval,
            expected_task_state_version=current.state_version,
        )
    return {"task": task.id, "version": version.id, "execution": execution_id}


DIAMOND = {
    "steps": [
        {"key": "gather", "type": "retrieve", "title": "找题"},
        {"key": "draft", "type": "generate", "title": "起草", "depends_on": ["gather"]},
        {"key": "verify", "type": "validate", "title": "校验", "depends_on": ["gather"]},
        {"key": "export", "type": "export", "title": "导出", "depends_on": ["draft", "verify"]},
    ]
}


async def scenario_materialise(uid: uuid.UUID) -> None:
    print("1. a valid DAG is materialised with steps and edges")
    ctx = await ready_task(uid, DIAMOND)
    async with db.session_for(uid) as s:
        counts = (
            await s.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM agent_plan_steps WHERE plan_version_id = :v) AS steps,
                        (SELECT count(*) FROM agent_step_dependencies WHERE plan_version_id = :v) AS edges
                    """
                ),
                {"v": ctx["version"]},
            )
        ).one()
    check(counts.steps == 4, f"4 steps stored (got {counts.steps})")
    check(counts.edges == 4, f"4 edges stored (got {counts.edges})")


async def scenario_invalid(uid: uuid.UUID) -> None:
    print("2. unexecutable plans are rejected before approval")
    cases = {
        "cycle": {"steps": [
            {"key": "a", "depends_on": ["b"]},
            {"key": "b", "depends_on": ["a"]},
        ]},
        "unknown dependency": {"steps": [{"key": "a", "depends_on": ["nope"]}]},
        "duplicate key": {"steps": [{"key": "a"}, {"key": "a"}]},
        "empty": {"steps": []},
        "self dependency": {"steps": [{"key": "a", "depends_on": ["a"]}]},
    }
    for label, content in cases.items():
        async with db.session_for(uid) as s:
            task = await tasks.create_task(s, uid, f"坏计划 {label}")
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
                    {"t": task.id, "o": uid, "h": "d" * 64,
                     "st": contract.load("requirement_version").initial},
                )
            ).scalar_one()
        rejected = False
        async with db.session_for(uid) as s:
            try:
                await plans.create_plan_version(s, uid, task.id, requirement, content)
            except steps.PlanDagError:
                rejected = True
        check(rejected, f"{label} rejected at creation")

        async with db.system_session() as s:
            left = (
                await s.execute(
                    text("SELECT count(*) FROM agent_plan_steps WHERE plan_version_id IN "
                         "(SELECT id FROM agent_plan_versions WHERE task_id = :t)"),
                    {"t": task.id},
                )
            ).scalar_one()
        check(left == 0, f"  {label}: nothing left behind")


async def scenario_scheduling(uid: uuid.UUID) -> None:
    print("3. only dependency-satisfied steps become ready")
    ctx = await ready_task(uid, DIAMOND)
    execution = ctx["execution"]

    async with db.session_for(uid) as s:
        ready = [r["step_key"] for r in await steps.ready_steps(s, execution)]
    check(ready == ["gather"], f"initially only 'gather' is ready (got {ready})")

    async with db.session_for(uid) as s:
        try:
            await steps.start_step(s, execution, "export")
            check(False, "a step with unfinished dependencies started")
        except steps.StepConflict:
            check(True, "starting 'export' early is refused")

    async with db.session_for(uid) as s:
        gather_id = await steps.start_step(s, execution, "gather")
    async with db.session_for(uid) as s:
        try:
            await steps.start_step(s, execution, "gather")
            check(False, "the same step started twice")
        except steps.StepConflict:
            check(True, "starting the same step twice is refused")

    async with db.session_for(uid) as s:
        await steps.finish_step(s, gather_id, succeeded=True)
    async with db.session_for(uid) as s:
        ready = sorted(r["step_key"] for r in await steps.ready_steps(s, execution))
    check(ready == ["draft", "verify"], f"both children are ready (got {ready})")

    # finish the two children, then the join must become ready
    for key in ("draft", "verify"):
        async with db.session_for(uid) as s:
            step_id = await steps.start_step(s, execution, key)
        async with db.session_for(uid) as s:
            await steps.finish_step(s, step_id, succeeded=True)

    async with db.session_for(uid) as s:
        ready = [r["step_key"] for r in await steps.ready_steps(s, execution)]
        done, failed = await steps.all_steps_settled(s, execution)
    check(ready == ["export"], f"the join becomes ready (got {ready})")
    check(not done and not failed, "not settled while 'export' is pending")

    async with db.session_for(uid) as s:
        step_id = await steps.start_step(s, execution, "export")
    async with db.session_for(uid) as s:
        await steps.finish_step(s, step_id, succeeded=True)
    async with db.session_for(uid) as s:
        done, failed = await steps.all_steps_settled(s, execution)
    check(done and not failed, "all four steps succeeded")

    # and only now may the execution advance on its own contract
    async with db.session_for(uid) as s:
        current = await executions.get_execution(s, execution)
    async with db.session_for(uid) as s:
        await s.execute(
            text("UPDATE agent_executions SET status = 'running', state_version = 3 WHERE id = :id"),
            {"id": execution},
        )
    async with db.session_for(uid) as s:
        result = await executions.advance_execution(
            s, execution, "steps_succeeded", expected_state_version=3
        )
    check(result.status == "succeeded", f"execution completes (got {result.status})")


async def scenario_failure(uid: uuid.UUID) -> None:
    print("4. a failed step blocks its dependents")
    ctx = await ready_task(uid, DIAMOND)
    execution = ctx["execution"]

    async with db.session_for(uid) as s:
        gather_id = await steps.start_step(s, execution, "gather")
    async with db.session_for(uid) as s:
        await steps.finish_step(s, gather_id, succeeded=False, error_code="RETRIEVAL_EMPTY")

    async with db.session_for(uid) as s:
        ready = [r["step_key"] for r in await steps.ready_steps(s, execution)]
        done, failed = await steps.all_steps_settled(s, execution)
    check(ready == [], f"children stay blocked (got {ready})")
    check(failed, "the failure is visible to the scheduler")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        uid = await make_user()
        await scenario_materialise(uid)
        await scenario_invalid(uid)
        await scenario_scheduling(uid)
        await scenario_failure(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: plan DAG is validated at creation and scheduled by dependencies")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
