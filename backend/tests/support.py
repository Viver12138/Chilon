"""Shared test support: run suites as a non-superuser role.

Every suite used to connect as `postgres`, which bypasses row-level security. That
hid five separate classes of missing write policy. Connecting as a real role is the
only way a test can prove the app works where it will actually run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROLE = "chilon_app_test"
PASSWORD = "app_test_only"

_admin_url: str | None = None


async def provision_runtime_role(url: str, *, role: str = ROLE, password: str = PASSWORD) -> str:
    """Create a login role with table privileges and return a URL that uses it.

    Deliberately no BYPASSRLS and no superuser: the point is to be exactly as
    restricted as production. `GRANT` on all tables is the deployment grant that a
    migration would perform.
    """
    global _admin_url
    _admin_url = url

    admin = create_async_engine(url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await conn.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
                )
            )
    finally:
        await admin.dispose()

    marker = "postgres:chilon_test_only@"
    if marker not in url:
        raise RuntimeError(
            "provision_runtime_role expects the test URL to contain "
            f"{marker!r} so it can swap the credentials; got {url!r}"
        )
    return url.replace(marker, f"{role}:{password}@")


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """A migration-role session, for fixtures that create platform content.

    Platform knowledge (`scope='platform'`, `owner_id` NULL) has **no** write policy
    for the application role, on purpose: a teacher must not be able to mint licensed
    content. Seeding it is an administrative act, so fixtures do it the way a
    migration would — with the admin role — instead of widening a policy to make a
    test pass.
    """
    if _admin_url is None:
        raise RuntimeError("call provision_runtime_role() before admin_session()")
    engine = create_async_engine(_admin_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            async with session.begin():
                yield session
    finally:
        await engine.dispose()

