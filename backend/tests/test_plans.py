"""Plan approval tests: the "agent proposes, teacher approves" contract.

The assertions target the ways this contract fails in practice:

* an approval reused for a second execution
* an approval carried over after the plan changed
* two executors both consuming the same approval
* an expired approval, or one that was never approved
* a database constraint that quietly forbids recording consumption at all
  (this one actually happened — see D.37)
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import contract, plans, tasks  # noqa: E402

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
            {"id": uid, "u": f"plan_{uid.hex[:10]}"},
        )
    return uid


async def make_task(uid: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "方案审批测试")
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
                    "hash": "a" * 64,
                    # never hard-code a state literal: take it from the contract
                    "status": contract.load("requirement_version").initial,
                },
            )
        ).scalar_one()
    return task.id, requirement


async def approved_approval(uid: uuid.UUID, plan_content: dict) -> tuple[uuid.UUID, uuid.UUID, str]:
    task_id, requirement = await make_task(uid)
    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(s, uid, task_id, requirement, plan_content)
    async with db.session_for(uid) as s:
        approval_id = await plans.request_approval(s, uid, task_id, version.id)
    async with db.session_for(uid) as s:
        await plans.decide(s, approval_id, uid, "approved")
    return approval_id, version.id, version.content_hash


async def scenario_plan_version(uid: uuid.UUID) -> None:
    print("1. plan version is created from the contract's initial state")
    task_id, requirement = await make_task(uid)
    async with db.session_for(uid) as s:
        v1 = await plans.create_plan_version(s, uid, task_id, requirement, {"steps": [{"key": "a"}]})
    check(v1.status == plans.PLAN_VERSION.initial, f"status is {v1.status!r} (contract initial)")
    check(v1.version_no == 1, "first version is numbered 1")

    async with db.session_for(uid) as s:
        v2 = await plans.create_plan_version(s, uid, task_id, requirement, {"steps": [{"key": "a"}]})
    check(v2.version_no == 2, "second version increments")
    check(v1.content_hash == v2.content_hash, "identical content hashes identically")

    async with db.session_for(uid) as s:
        v3 = await plans.create_plan_version(s, uid, task_id, requirement, {"steps": [{"key": "b"}]})
    check(v3.content_hash != v1.content_hash, "different content hashes differently")

    # key order must not change identity
    check(
        plans.content_hash({"a": 1, "b": 2}) == plans.content_hash({"b": 2, "a": 1}),
        "hash is canonical over key order",
    )


async def scenario_consumption(uid: uuid.UUID) -> None:
    print("2. consumption works once, and is recorded")
    approval_id, version_id, digest = await approved_approval(uid, {"steps": [{"key": "x"}]})

    async with db.session_for(uid) as s:
        await plans.consume_for_execution(s, approval_id, version_id, digest)
    async with db.session_for(uid) as s:
        row = (
            await s.execute(
                text("SELECT status, consumed_at FROM agent_plan_approvals WHERE id = :id"),
                {"id": approval_id},
            )
        ).one()
    check(row.consumed_at is not None, "consumed_at was recorded (the constraint allows it)")
    check(row.status == "approved", "status stays approved — consumption is a use, not a decision")

    async with db.session_for(uid) as s:
        try:
            await plans.consume_for_execution(s, approval_id, version_id, digest)
            check(False, "the same approval was consumed twice")
        except plans.ApprovalNotConsumable as exc:
            check("already consumed" in exc.reason, f"second consumption refused ({exc.reason})")


async def scenario_hash_binding(uid: uuid.UUID) -> None:
    print("3. an approval does not survive a change to the plan")
    approval_id, version_id, _ = await approved_approval(uid, {"steps": [{"key": "original"}]})
    async with db.session_for(uid) as s:
        try:
            await plans.consume_for_execution(s, approval_id, version_id, plans.content_hash({"steps": [{"key": "edited"}]}))
            check(False, "a changed plan was executed under the old approval")
        except plans.ApprovalNotConsumable as exc:
            check("content changed" in exc.reason, f"hash mismatch refused ({exc.reason})")

    async with db.session_for(uid) as s:
        row = (
            await s.execute(
                text("SELECT consumed_at FROM agent_plan_approvals WHERE id = :id"), {"id": approval_id}
            )
        ).one()
    check(row.consumed_at is None, "a refused consumption leaves the approval intact")


async def scenario_expiry(uid: uuid.UUID) -> None:
    print("4. an expired approval cannot authorise execution")
    approval_id, version_id, digest = await approved_approval(uid, {"steps": [{"key": "y"}]})
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with db.system_session() as s:
        await s.execute(
            text("UPDATE agent_plan_approvals SET expires_at = :t WHERE id = :id"),
            {"t": past, "id": approval_id},
        )
    async with db.session_for(uid) as s:
        try:
            await plans.consume_for_execution(s, approval_id, version_id, digest)
            check(False, "expired approval was consumed")
        except plans.ApprovalNotConsumable as exc:
            check(exc.reason == "expired", f"expiry refused ({exc.reason})")


async def scenario_not_approved(uid: uuid.UUID) -> None:
    print("5. pending and rejected approvals cannot be consumed")
    task_id, requirement = await make_task(uid)
    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(s, uid, task_id, requirement, {"steps": [{"key": "z"}]})
    async with db.session_for(uid) as s:
        approval_id = await plans.request_approval(s, uid, task_id, version.id)

    async with db.session_for(uid) as s:
        try:
            await plans.consume_for_execution(s, approval_id, version.id, version.content_hash)
            check(False, "a pending approval was consumed")
        except plans.ApprovalNotConsumable as exc:
            check("pending" in exc.reason, f"pending refused ({exc.reason})")

    async with db.session_for(uid) as s:
        await plans.decide(s, approval_id, uid, "rejected")
    async with db.session_for(uid) as s:
        try:
            await plans.consume_for_execution(s, approval_id, version.id, version.content_hash)
            check(False, "a rejected approval was consumed")
        except plans.ApprovalNotConsumable as exc:
            check("rejected" in exc.reason, f"rejected refused ({exc.reason})")

    # deciding twice must not flip a rejection into an approval
    async with db.session_for(uid) as s:
        try:
            await plans.decide(s, approval_id, uid, "approved")
            check(False, "a decided approval accepted a second decision")
        except plans.ApprovalNotConsumable:
            check(True, "second decision refused (CAS on status = pending)")


async def scenario_db_constraint(uid: uuid.UUID) -> None:
    print("6. the database refuses consumption on a non-approved row")
    task_id, requirement = await make_task(uid)
    async with db.session_for(uid) as s:
        version = await plans.create_plan_version(s, uid, task_id, requirement, {"steps": [{"key": "w"}]})
    async with db.session_for(uid) as s:
        approval_id = await plans.request_approval(s, uid, task_id, version.id)

    refused = False
    async with db.session_for(uid) as s:
        try:
            await s.execute(
                text("UPDATE agent_plan_approvals SET consumed_at = now() WHERE id = :id"),
                {"id": approval_id},
            )
        except Exception:  # noqa: BLE001 - any rejection is the point
            refused = True
    check(refused, "CHECK constraint blocks consumed_at unless status = 'approved'")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        uid = await make_user()
        await scenario_plan_version(uid)
        await scenario_consumption(uid)
        await scenario_hash_binding(uid)
        await scenario_expiry(uid)
        await scenario_not_approved(uid)
        await scenario_db_constraint(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: plan approval is single-use, hash-bound and expiry-aware")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
