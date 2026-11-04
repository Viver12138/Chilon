"""Transactional outbox dispatcher.

The contract (master §21.13):

* the business state change, the business event and the outbox row are written in
  **one** transaction;
* delivery is **at-least-once**, so consumers must be idempotent;
* a handler failure must never lose the event.

Mechanism: `FOR UPDATE SKIP LOCKED` inside the dispatching transaction.

Why not a `delivering` claim state: it would need a visibility timeout and a
reaper for crashed workers. For MVP the transaction *is* the claim — if the
process dies mid-handler the transaction rolls back, the event stays claimable,
and it is retried. The cost is that the row lock is held while the handler runs,
so handlers must stay short. When handlers get slow, the next step is a claim
state plus timeout, not a bigger timeout here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

Handler = Callable[["Event"], Awaitable[None]]

MAX_ATTEMPTS = 5
BATCH_SIZE = 20


@dataclass(frozen=True)
class Event:
    id: str
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    attempts: int


@dataclass
class DispatchResult:
    delivered: int = 0
    failed: int = 0
    dead_lettered: int = 0
    skipped: int = 0


async def enqueue(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Append an event inside the caller's transaction.

    Must be called with the same session that performs the business write; the
    caller's `async with session.begin()` is what makes the two atomic.
    """
    row = await session.execute(
        text(
            """
            INSERT INTO outbox_events
                (id, event_id, aggregate_type, aggregate_id, event_type, payload)
            VALUES
                (gen_random_uuid(), gen_random_uuid(), :aggregate_type, :aggregate_id,
                 :event_type, CAST(:payload AS jsonb))
            RETURNING event_id
            """
        ),
        {
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "event_type": event_type,
            "payload": __import__("json").dumps(payload, ensure_ascii=False),
        },
    )
    return str(row.scalar_one())


async def claim(session: AsyncSession, limit: int = BATCH_SIZE) -> list[Event]:
    """Lock a batch of claimable events for this transaction.

    `SKIP LOCKED` makes two dispatchers take disjoint rows instead of blocking or
    double-processing. Only `pending`/`failed` with `available_at <= now()` are
    eligible, so a backoff actually delays the retry.
    """
    rows = await session.execute(
        text(
            """
            SELECT id, event_id, aggregate_type, aggregate_id, event_type, payload, attempts
            FROM outbox_events
            WHERE status IN ('pending', 'failed')
              AND available_at <= now()
            ORDER BY available_at, created_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": limit},
    )
    return [
        Event(
            id=str(r.id),
            event_id=str(r.event_id),
            aggregate_type=r.aggregate_type,
            aggregate_id=str(r.aggregate_id),
            event_type=r.event_type,
            payload=r.payload,
            attempts=r.attempts,
        )
        for r in rows
    ]


async def dispatch_once(
    session: AsyncSession,
    handlers: Mapping[str, Handler],
    *,
    limit: int = BATCH_SIZE,
    max_attempts: int = MAX_ATTEMPTS,
) -> DispatchResult:
    """Claim, deliver and settle one batch. Runs inside the caller's transaction."""
    result = DispatchResult()
    for event in await claim(session, limit):
        handler = handlers.get(event.event_type)
        if handler is None:
            # An unhandled type is a deployment mistake, not a poison message:
            # leave it pending so fixing the handler is enough to drain it.
            logger.warning("no handler for event type %s", event.event_type)
            result.skipped += 1
            continue

        try:
            await handler(event)
        except Exception as exc:  # noqa: BLE001 - any handler failure is retryable
            attempts = event.attempts + 1
            if attempts >= max_attempts:
                await session.execute(
                    text(
                        """
                        UPDATE outbox_events
                        SET status = 'dead_letter', attempts = :attempts,
                            last_error = :err
                        WHERE id = :id
                        """
                    ),
                    {"attempts": attempts, "err": f"{type(exc).__name__}: {exc}", "id": event.id},
                )
                result.dead_lettered += 1
                logger.error("event %s dead-lettered after %s attempts", event.event_id, attempts)
            else:
                await session.execute(
                    text(
                        """
                        UPDATE outbox_events
                        SET status = 'failed', attempts = :attempts, last_error = :err,
                            available_at = now() + make_interval(secs => :backoff)
                        WHERE id = :id
                        """
                    ),
                    {
                        "attempts": attempts,
                        "err": f"{type(exc).__name__}: {exc}"[:2000],
                        # exponential backoff: 2s, 4s, 8s, 16s
                        "backoff": 2 ** attempts,
                        "id": event.id,
                    },
                )
                result.failed += 1
            continue

        await session.execute(
            text(
                """
                UPDATE outbox_events
                SET status = 'delivered', attempts = attempts + 1, delivered_at = now()
                WHERE id = :id
                """
            ),
            {"id": event.id},
        )
        result.delivered += 1

    return result
