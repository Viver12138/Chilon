"""Shared test support: run suites as a non-superuser role.

Every suite used to connect as `postgres`, which bypasses row-level security. That
hid five separate classes of missing write policy. Connecting as a real role is the
only way a test can prove the app works where it will actually run.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROLE = "chilon_app_test"
PASSWORD = "app_test_only"


async def provision_runtime_role(url: str, *, role: str = ROLE, password: str = PASSWORD) -> str:
    """Create a login role with table privileges and return a URL that uses it.

    Deliberately no BYPASSRLS and no superuser: the point is to be exactly as
    restricted as production. `GRANT` on all tables is the deployment grant that a
    migration would perform.
    """
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
