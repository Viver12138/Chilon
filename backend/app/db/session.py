"""Database session with row-level security context.

Every request runs inside a transaction that first stamps the session context:

    SELECT set_config('app.current_user_id', '<uuid>', true)

`true` means **transaction-local**: the setting disappears at COMMIT/ROLLBACK, so
a pooled connection can never leak one teacher's identity into the next request.
That property is the whole point — without it, RLS would silently return the
previous user's rows under load, which is the worst failure mode possible.

Use `session_for()`; never touch the engine directly from request code.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init(database_url: str, *, echo: bool = False) -> None:
    """Create the engine and session factory. Call once at application startup."""
    global _engine, _session_factory
    if _engine is not None:
        raise RuntimeError("database already initialised")
    # psycopg3 supports async natively; asyncpg cannot run multi-statement DDL.
    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_for(
    user_id: uuid.UUID,
    *,
    request_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction bound to one teacher's identity.

    The context is set inside the transaction that the caller uses, so the RLS
    policies (`owner_id = app_current_user_id()`) evaluate against it.
    """
    if _session_factory is None:
        raise RuntimeError("call init() before opening a session")

    async with _session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_user_id', :v, true)"),
                {"v": str(user_id)},
            )
            if request_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_request_id', :v, true)"),
                    {"v": str(request_id)},
                )
            if execution_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_execution_id', :v, true)"),
                    {"v": str(execution_id)},
                )
            yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Session without a user context, for maintenance jobs.

    It carries no `app.current_user_id`, so every owner-scoped policy evaluates
    to false: this session sees nothing unless the caller has real privileges.
    That is deliberate — a background job must opt in to a specific teacher
    rather than accidentally reading everyone.
    """
    if _session_factory is None:
        raise RuntimeError("call init() before opening a session")
    async with _session_factory() as session:
        async with session.begin():
            yield session
