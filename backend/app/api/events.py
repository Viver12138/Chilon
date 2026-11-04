"""SSE endpoint: `GET /conversations/{id}/events` (D5's declared stream)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.api.deps import ApiError, UserDep
from app.db import session as db
from app.services import event_stream

router = APIRouter(tags=["events"])


@router.get("/conversations/{conversation_id}/events")
async def conversation_events(
    conversation_id: uuid.UUID,
    request: Request,
    user: UserDep,
    last_event_id: Annotated[str | None, Header()] = None,
    from_seq: Annotated[int | None, Query()] = None,
) -> StreamingResponse:
    """Stream one conversation's events.

    Ownership is checked before the stream opens so a missing conversation is a 404
    rather than an empty stream that looks like "nothing happening yet".
    """
    async with db.session_for(user) as session:
        exists = (
            await session.execute(
                text("SELECT 1 FROM conversations WHERE id = :id"), {"id": conversation_id}
            )
        ).first()
    if exists is None:
        raise ApiError(404, "NOT_FOUND", "conversation not found")

    # the header wins over the query parameter when both are present
    resume_from = 0
    raw = last_event_id or (str(from_seq) if from_seq is not None else None)
    if raw:
        try:
            resume_from = int(raw)
        except ValueError:
            raise ApiError(422, "AST_INVALID", f"Last-Event-ID must be an integer, got {raw!r}")

    generator = event_stream.stream(user, conversation_id, last_event_id=resume_from)

    async def bounded():
        async for frame in generator:
            if await request.is_disconnected():
                break
            yield frame

    return StreamingResponse(
        bounded(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
