"""Conversation event stream (SSE).

The contract (D5) is specific and worth following exactly:

* the source of truth is `conversation_events` — Postgres, not a message bus;
* `Last-Event-ID` is the event sequence, and a reconnect replays from it before
  consuming anything live;
* sequence numbers are assigned per conversation inside the writing transaction.

Without Redis, the "live" half is a short-interval poll of the same table. That is
**strictly correct** — it can only ever be slower, never wrong — and the code says so
instead of pretending a bus exists.

Two implementation decisions that matter more than they look:

1. **No session is held open for the life of the stream.** Each replay/poll batch
   opens a short transaction. A stream that keeps a transaction open for minutes
   would hold a connection and block vacuum for no reason.
2. **Replay is bounded by the high-water mark taken at connect.** Events written
   during replay are picked up by the following poll, so a client cannot miss an
   event that lands exactly at the boundary, and cannot see one twice either.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db

HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 0.2


def format_frame(seq: int, event_type: str, data: dict[str, Any]) -> str:
    """One SSE frame. `id` must be the sequence so Last-Event-ID can resume."""
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {event_type}\ndata: {body}\n\n"


def format_heartbeat() -> str:
    """A comment frame: keeps proxies from closing an idle stream."""
    return ": ping\n\n"


async def append_event(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    aggregate: str = "execution",
    aggregate_id: uuid.UUID | None = None,
) -> int:
    """Append one event and return its sequence number.

    The sequence is computed with `max(seq)+1` inside the caller's transaction. Two
    concurrent appends to the same conversation therefore conflict on the unique
    constraint rather than silently sharing a number — losing the race is correct,
    because the caller retries with a fresh read.
    """
    seq = (
        await session.execute(
            text(
                "SELECT COALESCE(max(seq), 0) + 1 FROM conversation_events WHERE conversation_id = :c"
            ),
            {"c": conversation_id},
        )
    ).scalar_one()

    occurred_at = datetime.now().astimezone()
    await session.execute(
        text(
            """
            INSERT INTO conversation_events (id, conversation_id, seq, event_type, payload)
            VALUES (gen_random_uuid(), :conversation, :seq, :type, CAST(:payload AS jsonb))
            """
        ),
        {
            "conversation": conversation_id,
            "seq": seq,
            "type": event_type,
            "payload": json.dumps(
                {
                    "seq": seq,
                    "type": event_type,
                    "aggregate": aggregate,
                    "aggregate_id": str(aggregate_id) if aggregate_id else str(conversation_id),
                    "occurred_at": occurred_at.isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
        },
    )
    return seq


async def high_water_mark(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                text("SELECT COALESCE(max(seq), 0) FROM conversation_events WHERE conversation_id = :c"),
                {"c": conversation_id},
            )
        ).scalar_one()
    )


async def _events_after(
    session: AsyncSession, conversation_id: uuid.UUID, after_seq: int, upto_seq: int, limit: int = 100
) -> list[tuple[int, str, dict[str, Any]]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT seq, event_type, payload
                FROM conversation_events
                WHERE conversation_id = :c AND seq > :after AND seq <= :upto
                ORDER BY seq
                LIMIT :limit
                """
            ),
            {"c": conversation_id, "after": after_seq, "upto": upto_seq, "limit": limit},
        )
    ).all()
    return [(int(r.seq), r.event_type, r.payload) for r in rows]


async def stream(
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    last_event_id: int = 0,
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    max_events: int | None = None,
    max_idle_polls: int | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames: replay to the high-water mark, then follow live.

    `max_events` and `max_idle_polls` exist so tests can bound the stream; production
    passes neither and the stream ends when the client disconnects.
    """
    async with db.session_for(user_id) as session:
        watermark = await high_water_mark(session, conversation_id)

    cursor = last_event_id
    delivered = 0
    idle_polls = 0
    loop = asyncio.get_running_loop()
    # the heartbeat timer starts when the stream starts: a baseline of 0 would make
    # the first idle poll emit a ping before the client has seen any data
    last_heartbeat = loop.time()

    while True:
        batch: list[tuple[int, str, dict[str, Any]]] = []
        async with db.session_for(user_id) as session:
            batch = await _events_after(session, conversation_id, cursor, watermark)
            if not batch:
                # nothing left in the replay window; extend it to whatever is new
                watermark = await high_water_mark(session, conversation_id)
                batch = await _events_after(session, conversation_id, cursor, watermark)

        if batch:
            idle_polls = 0
            for seq, event_type, payload in batch:
                cursor = seq
                delivered += 1
                yield format_frame(seq, event_type, payload)
                if max_events is not None and delivered >= max_events:
                    return
            continue

        idle_polls += 1
        if max_idle_polls is not None and idle_polls > max_idle_polls:
            return

        now = loop.time()
        if now - last_heartbeat >= heartbeat_seconds:
            last_heartbeat = now
            yield format_heartbeat()

        await asyncio.sleep(poll_seconds)
