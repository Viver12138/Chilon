"""Outbox correctness tests.

Each scenario asserts one property of the delivery contract:

1. atomicity   - the business row and the outbox row survive or vanish together
2. delivery    - a dispatched event reaches its handler and is marked delivered
3. retry       - a handler failure keeps the event and backs off
4. dead letter - repeated failures stop retrying instead of looping forever
5. claim       - two dispatchers never lock the same event (SKIP LOCKED)
6. idempotency - a redelivered event does not repeat the consumer's side effect

Run against a disposable database:
    CHILON_TEST_DATABASE_URL=postgresql+psycopg://... python backend/tests/test_outbox.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db import session as db  # noqa: E402
from app.outbox import dispatcher  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def make_user(email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    async with db.session_for(uid) as s:
        await s.execute(
            text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
            {"id": uid, "u": email},
        )
    return uid


async def outbox_count(uid: uuid.UUID) -> tuple[int, int]:
    async with db.system_session() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT count(*) FILTER (WHERE status = 'pending') AS pending,
                           count(*) AS total
                    FROM outbox_events WHERE aggregate_id = :id
                    """
                ),
                {"id": uid},
            )
        ).one()
        return int(row.pending), int(row.total)


async def scenario_atomicity(uid: uuid.UUID) -> None:
    print("1. atomicity: business write and outbox row are one transaction")
    before = await outbox_count(uid)

    class Boom(Exception):
        pass

    try:
        async with db.session_for(uid) as s:
            await s.execute(
                text("INSERT INTO tasks (id, owner_id, title, created_by) VALUES (:id, :o, :t, :o)"),
                {"id": uuid.uuid4(), "o": uid, "t": "should-not-exist"},
            )
            await dispatcher.enqueue(
                s,
                aggregate_type="task",
                aggregate_id=str(uid),
                event_type="task.created",
                payload={"title": "should-not-exist"},
            )
            raise Boom("simulated crash before commit")
    except Boom:
        pass

    after = await outbox_count(uid)
    async with db.system_session() as s:
        tasks = (
            await s.execute(text("SELECT count(*) FROM tasks WHERE title = 'should-not-exist'"))
        ).scalar_one()

    check(after == before, "outbox row rolled back with the business write")
    check(tasks == 0, "task row rolled back")


async def scenario_delivery(uid: uuid.UUID) -> None:
    print("2. delivery: event reaches the handler and is marked delivered")
    delivered: list[str] = []

    async def handler(event: dispatcher.Event) -> None:
        delivered.append(event.event_type)

    async with db.session_for(uid) as s:
        event_id = await dispatcher.enqueue(
            s,
            aggregate_type="task",
            aggregate_id=str(uid),
            event_type="task.approved",
            payload={"n": 1},
        )

    async with db.system_session() as s:
        result = await dispatcher.dispatch_once(s, {"task.approved": handler})

    check(result.delivered >= 1, "dispatcher reported at least one delivery")
    check("task.approved" in delivered, "handler received the event")
    async with db.system_session() as s:
        status = (
            await s.execute(
                text("SELECT status FROM outbox_events WHERE event_id = :e"), {"e": event_id}
            )
        ).scalar_one()
    check(status == "delivered", f"status is delivered (got {status})")


async def scenario_retry(uid: uuid.UUID) -> None:
    print("3. retry: handler failure keeps the event and backs off")

    async def boom(event: dispatcher.Event) -> None:
        raise RuntimeError("downstream unavailable")

    async with db.session_for(uid) as s:
        await dispatcher.enqueue(
            s,
            aggregate_type="task",
            aggregate_id=str(uid),
            event_type="task.retry_me",
            payload={},
        )

    async with db.system_session() as s:
        await dispatcher.dispatch_once(s, {"task.retry_me": boom})

    async with db.system_session() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT status, attempts, available_at > now() AS backed_off, last_error
                    FROM outbox_events WHERE event_type = 'task.retry_me'
                    """
                )
            )
        ).one()

    check(row.status == "failed", f"status is failed (got {row.status})")
    check(row.attempts == 1, f"attempts counted (got {row.attempts})")
    check(bool(row.backed_off), "available_at moved into the future")
    check("downstream unavailable" in (row.last_error or ""), "error recorded")


async def scenario_dead_letter(uid: uuid.UUID) -> None:
    print("4. dead letter: repeated failures stop retrying")

    async def boom(event: dispatcher.Event) -> None:
        raise RuntimeError("permanent")

    async with db.session_for(uid) as s:
        await dispatcher.enqueue(
            s,
            aggregate_type="task",
            aggregate_id=str(uid),
            event_type="task.poison",
            payload={},
        )

    async with db.system_session() as s:
        await s.execute(
            text(
                "UPDATE outbox_events SET attempts = 4, status = 'failed' "
                "WHERE event_type = 'task.poison'"
            )
        )
        await dispatcher.dispatch_once(s, {"task.poison": boom}, max_attempts=5)

    async with db.system_session() as s:
        status = (
            await s.execute(
                text("SELECT status FROM outbox_events WHERE event_type = 'task.poison'")
            )
        ).scalar_one()
    check(status == "dead_letter", f"moved to dead_letter (got {status})")


async def scenario_claim_isolation(uid: uuid.UUID) -> None:
    print("5. claim: two dispatchers lock disjoint batches (SKIP LOCKED)")

    async with db.session_for(uid) as s:
        for i in range(3):
            await dispatcher.enqueue(
                s,
                aggregate_type="task",
                aggregate_id=str(uid),
                event_type=f"task.claim_{i}",
                payload={"i": i},
            )

    async with db.system_session() as a, db.system_session() as b:
        first = await dispatcher.claim(a, 1)
        second = await dispatcher.claim(b, 50)  # must skip the row locked above
        ids_a = {e.id for e in first}
        ids_b = {e.id for e in second}
        check(len(ids_a) == 1, "first dispatcher claimed exactly one row")
        check(not (ids_a & ids_b), "second dispatcher skipped the locked row")
        check(len(ids_b) >= 2, f"remaining rows still claimable (got {len(ids_b)})")


async def scenario_consumer_idempotency(uid: uuid.UUID) -> None:
    print("6. idempotency: a redelivered event does not repeat the side effect")
    seen: set[str] = set()
    effects = 0

    async def once_only(event: dispatcher.Event) -> None:
        nonlocal effects
        if event.event_id in seen:
            return
        seen.add(event.event_id)
        effects += 1

    async with db.session_for(uid) as s:
        event_id = await dispatcher.enqueue(
            s,
            aggregate_type="task",
            aggregate_id=str(uid),
            event_type="task.once",
            payload={},
        )

    async with db.system_session() as s:
        await dispatcher.dispatch_once(s, {"task.once": once_only})

    # simulate at-least-once redelivery of the very same event
    async with db.system_session() as s:
        await s.execute(
            text(
                "UPDATE outbox_events SET status = 'pending', delivered_at = NULL, "
                "available_at = now() WHERE event_id = :e"
            ),
            {"e": event_id},
        )
        await dispatcher.dispatch_once(s, {"task.once": once_only})

    check(effects == 1, f"side effect happened once despite two deliveries (got {effects})")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        uid = await make_user(f"outbox_{uuid.uuid4().hex[:8]}")
        await scenario_atomicity(uid)
        await scenario_delivery(uid)
        await scenario_retry(uid)
        await scenario_dead_letter(uid)
        await scenario_claim_isolation(uid)
        await scenario_consumer_idempotency(uid)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: outbox contract holds (atomic, at-least-once, idempotent, bounded retries)")
    return 0


if __name__ == "__main__":
    # psycopg async cannot run on Windows' default ProactorEventLoop. Production
    # is Linux, so this only affects local test runs on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
