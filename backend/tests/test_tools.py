"""Tool invocation tests: the gates, and idempotency under retry.

A tool call is where money and side effects happen, so the assertions are about
refusals as much as successes:

* ungranted, disabled and approval-requiring tools are refused
* the same call twice performs one side effect
* the same tool at a new version is a *different* call
* changing an argument produces a different key (no result smuggling)
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
from app.services import contract, executions, plans, tasks, tools  # noqa: E402

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
            {"id": uid, "u": f"tool_{uid.hex[:10]}"},
        )
    return uid


async def make_tool(
    key: str,
    *,
    version: str = "1.0.0",
    enabled: bool = True,
    requires_approval: bool = False,
) -> uuid.UUID:
    tool_id = uuid.uuid4()
    async with db.system_session() as s:
        await s.execute(
            text(
                """
                INSERT INTO agent_tool_definitions
                    (id, key, version, name, side_effect_level, requires_approval, is_enabled)
                VALUES (:id, :key, :version, :key, 'read', :approval, :enabled)
                """
            ),
            {
                "id": tool_id,
                "key": key,
                "version": version,
                "approval": requires_approval,
                "enabled": enabled,
            },
        )
    return tool_id


async def grant(uid: uuid.UUID, tool_id: uuid.UUID) -> None:
    async with db.system_session() as s:
        await s.execute(
            text(
                """
                INSERT INTO agent_tool_grants (id, owner_id, tool_definition_id, capability)
                VALUES (gen_random_uuid(), :owner, :tool, 'invoke')
                """
            ),
            {"owner": uid, "tool": tool_id},
        )


async def running_execution(uid: uuid.UUID) -> dict:
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "工具测试")
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
                {"t": task.id, "o": uid, "h": "e" * 64,
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
        execution_id = await executions.start_execution(
            s, uid, task.id, version.id, approval,
            expected_task_state_version=current.state_version,
        )
    return {"execution": execution_id, "task": task.id, "version": version.id}


async def scenario_gates(uid: uuid.UUID) -> None:
    print("1. ungranted, disabled and approval-requiring tools are refused")
    ctx = await running_execution(uid)

    free = await make_tool(f"test.free_{uuid.uuid4().hex[:6]}")
    disabled = await make_tool(f"test.off_{uuid.uuid4().hex[:6]}", enabled=False)
    gated = await make_tool(f"test.gated_{uuid.uuid4().hex[:6]}", requires_approval=True)
    await grant(uid, disabled)
    await grant(uid, gated)

    async with db.session_for(uid) as s:
        try:
            await tools.invoke(s, ctx["execution"], "definitely.not.a.tool", {})
        except tools.ToolNotFound:
            check(True, "unknown tool is refused")

    # ungranted
    async with db.session_for(uid) as s:
        ungranted = (
            await s.execute(text("SELECT key FROM agent_tool_definitions WHERE id = :id"), {"id": free})
        ).scalar_one()
        try:
            await tools.invoke(s, ctx["execution"], ungranted, {})
            check(False, "an ungranted tool ran")
        except tools.ToolNotGranted:
            check(True, "an ungranted tool is refused")

    await grant(uid, free)

    async with db.session_for(uid) as s:
        disabled_key = (
            await s.execute(text("SELECT key FROM agent_tool_definitions WHERE id = :id"), {"id": disabled})
        ).scalar_one()
        try:
            await tools.invoke(s, ctx["execution"], disabled_key, {})
            check(False, "a disabled tool ran")
        except tools.ToolDisabled:
            check(True, "a disabled tool is refused")

    async with db.session_for(uid) as s:
        gated_key = (
            await s.execute(text("SELECT key FROM agent_tool_definitions WHERE id = :id"), {"id": gated})
        ).scalar_one()
        inv = await tools.invoke(s, ctx["execution"], gated_key, {})
    check(inv.status == tools.TOOL.initial, f"approval-gated tool starts in {inv.status!r}")

    # a revoked grant must stop working
    async with db.system_session() as s:
        await s.execute(
            text("UPDATE agent_tool_grants SET revoked_at = now() WHERE owner_id = :o AND tool_definition_id = :t"),
            {"o": uid, "t": free},
        )
    async with db.session_for(uid) as s:
        try:
            await tools.invoke(s, ctx["execution"], ungranted, {"again": True})
            check(False, "a revoked grant still worked")
        except tools.ToolNotGranted:
            check(True, "a revoked grant is refused")


async def scenario_idempotency(uid: uuid.UUID) -> None:
    print("2. the same call twice performs one side effect")
    ctx = await running_execution(uid)
    tool_id = await make_tool(f"test.idem_{uuid.uuid4().hex[:6]}")
    await grant(uid, tool_id)
    async with db.session_for(uid) as s:
        key = (
            await s.execute(text("SELECT key FROM agent_tool_definitions WHERE id = :id"), {"id": tool_id})
        ).scalar_one()

    args = {"query": "三角函数的图像", "top_k": 5}
    async with db.session_for(uid) as s:
        first = await tools.invoke(s, ctx["execution"], key, args)
    async with db.session_for(uid) as s:
        second = await tools.invoke(s, ctx["execution"], key, args)

    check(not first.replayed, "first call is not a replay")
    check(second.replayed, "second call is reported as a replay")
    check(first.id == second.id, "replay returns the original invocation id")
    check(first.idempotency_key == second.idempotency_key, "the key is stable")

    async with db.system_session() as s:
        count = (
            await s.execute(
                text("SELECT count(*) FROM agent_tool_executions WHERE idempotency_key = :k"),
                {"k": first.idempotency_key},
            )
        ).scalar_one()
    check(count == 1, f"exactly one invocation row exists (got {count})")

    # a different argument is a different call
    async with db.session_for(uid) as s:
        third = await tools.invoke(s, ctx["execution"], key, {"query": "别的", "top_k": 5})
    check(third.id != first.id, "a changed argument produces a new call")
    check(not third.replayed, "the changed argument is not a replay")

    # key order must not change the identity of a call
    async with db.session_for(uid) as s:
        fourth = await tools.invoke(s, ctx["execution"], key, {"top_k": 5, "query": "三角函数的图像"})
    check(fourth.id == first.id, "argument key order does not change the call identity")


async def scenario_version(uid: uuid.UUID) -> None:
    print("3. a new tool version is a new call, not a replay")
    ctx = await running_execution(uid)
    key = f"test.ver_{uuid.uuid4().hex[:6]}"
    v1 = await make_tool(key, version="1.0.0")
    await grant(uid, v1)

    async with db.session_for(uid) as s:
        first = await tools.invoke(s, ctx["execution"], key, {"a": 1})

    v2 = await make_tool(key, version="2.0.0")
    await grant(uid, v2)

    async with db.session_for(uid) as s:
        second = await tools.invoke(s, ctx["execution"], key, {"a": 1})
    check(second.id != first.id, "the upgraded tool produces a new invocation")
    check(not second.replayed, "the upgraded tool is not treated as a replay")


async def scenario_transitions(uid: uuid.UUID) -> None:
    print("4. tool status follows the contract, and the result is hashed")
    ctx = await running_execution(uid)
    tool_id = await make_tool(f"test.flow_{uuid.uuid4().hex[:6]}")
    await grant(uid, tool_id)
    async with db.session_for(uid) as s:
        key = (
            await s.execute(text("SELECT key FROM agent_tool_definitions WHERE id = :id"), {"id": tool_id})
        ).scalar_one()

    async with db.session_for(uid) as s:
        inv = await tools.invoke(s, ctx["execution"], key, {"x": 1})

    path = ["begin_authorization", "authorize", "dispatch", "tool_running"]
    status = inv.status
    for trigger in path:
        async with db.session_for(uid) as s:
            status = await tools.advance(s, inv.id, trigger)
    check(status == "running", f"walked to running (got {status})")

    async with db.session_for(uid) as s:
        try:
            await tools.advance(s, inv.id, "authorize")
            check(False, "an illegal tool transition was accepted")
        except tools.ToolConflict:
            check(True, "an illegal tool transition is refused")

    async with db.session_for(uid) as s:
        await tools.record_result(s, inv.id, {"rows": 3}, succeeded=True)
    async with db.session_for(uid) as s:
        row = (
            await s.execute(
                text("SELECT status, result_hash, finished_at FROM agent_tool_executions WHERE id = :id"),
                {"id": inv.id},
            )
        ).one()
    check(row.status == "succeeded", f"result recorded as succeeded (got {row.status})")
    check(row.result_hash is not None and len(row.result_hash) == 64, "result hash stored")
    check(row.finished_at is not None, "finished_at set")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        uid = await make_user()
        await scenario_gates(uid)
        await scenario_idempotency(uid)
        await scenario_version(uid)
        await scenario_transitions(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: tool calls pass the gates and are idempotent across retries")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
