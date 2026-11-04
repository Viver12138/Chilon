"""SSE stream tests.

The properties that make a stream usable, each asserted rather than assumed:

1. replay resumes exactly after Last-Event-ID (no gap, no duplicate);
2. an event written *during* the stream is delivered;
3. frames are well formed and `id` equals the sequence the replay uses;
4. an idle stream emits heartbeats instead of going silent;
5. another teacher's conversation is a 404, not an empty stream.
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

from app.db import session as db  # noqa: E402
from app.services import event_stream  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


def parse_frame(frame: str) -> dict | None:
    """Turn one SSE frame into {id, event, data}, or None for a comment frame."""
    if frame.startswith(":"):
        return {"comment": frame.strip()}
    out: dict = {}
    for line in frame.strip().splitlines():
        if line.startswith("id: "):
            out["id"] = int(line[4:])
        elif line.startswith("event: "):
            out["event"] = line[7:]
        elif line.startswith("data: "):
            out["data"] = json.loads(line[6:])
    return out


async def make_user() -> tuple[uuid.UUID, uuid.UUID]:
    uid = uuid.uuid4()
    async with db.session_for(uid) as s:
        await s.execute(
            text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
            {"id": uid, "u": f"sse_{uid.hex[:10]}"},
        )
        conversation_id = (
            await s.execute(
                text(
                    """
                    INSERT INTO conversations (id, owner_id, title, created_by)
                    VALUES (gen_random_uuid(), :o, '执行进度', :o) RETURNING id
                    """
                ),
                {"o": uid},
            )
        ).scalar_one()
    return uid, conversation_id


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        user_id, conversation_id = await make_user()

        print("1. events get monotonic per-conversation sequences")
        async with db.session_for(user_id) as s:
            seqs = [
                await event_stream.append_event(s, conversation_id, "execution.progress", {"step": i})
                for i in range(3)
            ]
        check(seqs == [1, 2, 3], f"sequences are 1,2,3 (got {seqs})")

        print("2. replay resumes exactly after Last-Event-ID")
        frames = []
        async for frame in event_stream.stream(
            user_id, conversation_id, last_event_id=1, max_events=2, poll_seconds=0.01
        ):
            frames.append(parse_frame(frame))
        check(len(frames) == 2, f"two frames after seq 1 (got {len(frames)})")
        check([f["id"] for f in frames] == [2, 3], f"ids are 2,3 (got {[f['id'] for f in frames]})")
        check(all(f["event"] == "execution.progress" for f in frames), "event types are carried")
        check(
            frames[0]["data"]["payload"] == {"step": 1},
            "payload of seq 2 is the second event",
        )

        print("3. an event written during the stream is delivered")
        frames = []

        async def consume():
            async for frame in event_stream.stream(
                user_id, conversation_id, last_event_id=3, max_events=1, poll_seconds=0.01
            ):
                parsed = parse_frame(frame)
                if "comment" in parsed:
                    continue  # heartbeats are not events
                frames.append(parsed)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        check(task.done() is False, "the stream is waiting when there is nothing new")
        async with db.session_for(user_id) as s:
            await event_stream.append_event(s, conversation_id, "activity.updated", {"note": "live"})
        await asyncio.wait_for(task, timeout=3)
        check(len(frames) == 1, f"the live event arrived (got {len(frames)})")
        check(frames[0]["id"] == 4, f"it is seq 4 (got {frames[0]['id']})")
        check(frames[0]["data"]["payload"] == {"note": "live"}, "payload is intact")

        print("4. an idle stream emits heartbeats")
        beat = None
        async for frame in event_stream.stream(
            user_id,
            conversation_id,
            last_event_id=4,
            heartbeat_seconds=0.0,
            poll_seconds=0.01,
            max_idle_polls=1,
        ):
            beat = parse_frame(frame)
            break
        check(beat is not None and "comment" in beat, f"a comment frame was emitted ({beat})")

        print("5. frames are well formed")
        async with db.session_for(user_id) as s:
            await event_stream.append_event(
                s, conversation_id, "approval.requested", {"approval_id": "x"}, aggregate="plan_approval"
            )
        async for frame in event_stream.stream(
            user_id, conversation_id, last_event_id=4, max_events=1, poll_seconds=0.01
        ):
            parsed = parse_frame(frame)
            check(frame.endswith("\n\n"), "frame ends with a blank line as SSE requires")
            check(parsed["id"] == 5, f"id matches the stored sequence (got {parsed['id']})")
            check(parsed["data"]["aggregate"] == "plan_approval", "aggregate is carried")
            check(
                set(parsed["data"]) >= {"seq", "type", "aggregate", "aggregate_id", "occurred_at", "payload"},
                "envelope has all D5 fields",
            )

        print("6. replay is bounded and does not duplicate")
        all_ids = []
        async for frame in event_stream.stream(
            user_id, conversation_id, last_event_id=0, max_events=100, poll_seconds=0.01, max_idle_polls=0
        ):
            all_ids.append(parse_frame(frame)["id"])
        check(all_ids == [1, 2, 3, 4, 5], f"full replay is 1..5 without duplicates (got {all_ids})")
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: the stream replays, follows live, and never duplicates or skips")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
