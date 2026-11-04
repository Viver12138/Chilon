"""Task lifecycle tests, driven by the contract rather than by hand-written cases.

The point is coverage of the *whole* transition matrix, not a few happy paths:

1. every contract transition succeeds and lands on the declared state
2. every (state, trigger) pair the contract does not declare is rejected
3. a stale `state_version` is rejected and leaves no event behind
4. every successful transition writes exactly one outbox event, in-transaction

If someone edits `state_machines.v1.json`, these tests change behaviour without
being touched — which is the whole reason the service reads the contract.

Run against a disposable database:
    CHILON_TEST_DATABASE_URL=postgresql+psycopg://... python backend/tests/test_tasks.py
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
from app.services import tasks  # noqa: E402

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
            {"id": uid, "u": f"task_{uid.hex[:10]}"},
        )
    return uid


async def new_task(uid: uuid.UUID, state: str) -> uuid.UUID:
    async with db.session_for(uid) as s:
        task = await tasks.create_task(s, uid, "测试任务")
    async with db.session_for(uid) as s:
        await s.execute(
            text("UPDATE tasks SET status = :st, state_version = 7 WHERE id = :id"),
            {"st": state, "id": task.id},
        )
    return task.id


async def events_for(task_id: uuid.UUID) -> list[dict]:
    async with db.system_session() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT event_type, payload FROM outbox_events
                    WHERE aggregate_id = :id ORDER BY created_at, id
                    """
                ),
                {"id": task_id},
            )
        ).all()
    return [{"type": r.event_type, "payload": r.payload} for r in rows]


async def scenario_every_legal_transition(uid: uuid.UUID) -> None:
    print(f"1. all {len(tasks.TRANSITIONS)} contract transitions succeed")
    for (from_state, trigger), transition in sorted(tasks.TRANSITIONS.items()):
        task_id = await new_task(uid, from_state)
        async with db.session_for(uid) as s:
            result = await tasks.advance(
                s, task_id, trigger, expected_state_version=7, actor_id=uid
            )
        ok = result.status == transition.to_state and result.state_version == 8
        check(ok, f"{from_state} --{trigger}--> {transition.to_state}")
        if not ok:
            print(f"         got {result.status} v{result.state_version}")

        events = await events_for(task_id)
        changed = [e for e in events if e["type"] == "task.status_changed"]
        payload_ok = (
            len(changed) == 1
            and changed[0]["payload"]["from"] == from_state
            and changed[0]["payload"]["to"] == transition.to_state
            and changed[0]["payload"]["trigger"] == trigger
        )
        check(payload_ok, f"  {transition.id} wrote exactly one event with from/to/trigger")


async def scenario_every_illegal_pair(uid: uuid.UUID) -> None:
    print("2. every undeclared (state, trigger) pair is rejected")
    triggers = sorted({trigger for (_, trigger) in tasks.TRANSITIONS})
    illegal = 0
    accepted = []

    state_ids: dict[str, uuid.UUID] = {}
    for state in tasks.STATES:
        state_ids[state] = await new_task(uid, state)

    for state in tasks.STATES:
        for trigger in triggers:
            if (state, trigger) in tasks.TRANSITIONS:
                continue
            illegal += 1
            task_id = state_ids[state]
            async with db.session_for(uid) as s:
                try:
                    await tasks.advance(s, task_id, trigger, expected_state_version=7)
                    accepted.append((state, trigger))
                except tasks.IllegalTransition as exc:
                    if exc.state != state or exc.trigger != trigger:
                        accepted.append((state, trigger, "wrong error payload"))

    check(not accepted, f"{illegal} illegal pairs checked, all rejected")
    if accepted:
        for item in accepted[:5]:
            print(f"         accepted: {item}")

    # the rejected calls must not have moved anything
    async with db.session_for(uid) as s:
        for state, task_id in state_ids.items():
            current = await tasks.get_task(s, task_id)
            check(
                current.status == state and current.state_version == 7,
                f"state {state!r} unchanged after rejected attempts",
            )


async def scenario_cas(uid: uuid.UUID) -> None:
    print("3. a stale state_version is rejected and leaves no event")
    task_id = await new_task(uid, "draft")
    before = await events_for(task_id)

    async with db.session_for(uid) as s:
        try:
            await tasks.advance(s, task_id, "submit_requirement", expected_state_version=6)
            check(False, "stale state_version was accepted")
        except tasks.StateConflict as exc:
            check(exc.expected == 6, "StateConflict reports the version the caller used")
        except Exception as exc:  # noqa: BLE001
            check(False, f"unexpected error for stale version: {type(exc).__name__}")

    async with db.session_for(uid) as s:
        current = await tasks.get_task(s, task_id)
    check(current.status == "draft" and current.state_version == 7, "state did not move")

    after = await events_for(task_id)
    check(len(after) == len(before), "no event was written for the rejected call")

    # the same trigger with the right version must succeed
    async with db.session_for(uid) as s:
        moved = await tasks.advance(s, task_id, "submit_requirement", expected_state_version=7)
    check(moved.status == "planning", f"correct version moves the task (got {moved.status})")


async def scenario_unknown_task(uid: uuid.UUID) -> None:
    print("4. unknown task is rejected, not silently created")
    async with db.session_for(uid) as s:
        try:
            await tasks.advance(s, uuid.uuid4(), "submit_requirement", expected_state_version=0)
            check(False, "unknown task was accepted")
        except tasks.TaskNotFound:
            check(True, "unknown task raises TaskNotFound")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        uid = await make_user()
        await scenario_every_legal_transition(uid)
        await scenario_every_illegal_pair(uid)
        await scenario_cas(uid)
        await scenario_unknown_task(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: task service matches the contract for every declared and undeclared transition")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
