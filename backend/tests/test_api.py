"""HTTP layer tests against a real database.

These assert the contract at the boundary: status codes, the frozen error codes,
and that the RLS context actually comes from the bearer token rather than from
anything in the request body.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import identity, plans, tasks  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def make_user() -> tuple[uuid.UUID, str]:
    uid = uuid.uuid4()
    username = f"api_{uid.hex[:10]}"
    async with db.system_session() as s:
        await identity.register(s, username, "pw12345678")
        session = await identity.login(s, username, "pw12345678")
    return session.user_id, session.token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def scenario_auth(client: httpx.AsyncClient) -> tuple[uuid.UUID, str]:
    print("1. authentication is a dependency, not an endpoint")
    _, token = await make_user()

    r = await client.get("/tasks")
    check(r.status_code == 401, f"no token is refused (got {r.status_code})")
    check(r.json()["error"]["code"] == "FORBIDDEN", "the error code is frozen, not invented")

    r = await client.get("/tasks", headers=auth("not-a-token"))
    check(r.status_code == 401, f"a bogus token is refused (got {r.status_code})")

    uid, token = await make_user()
    r = await client.get("/tasks", headers=auth(token))
    check(r.status_code == 200, f"a real token works (got {r.status_code})")
    return uid, token


async def scenario_task_flow(client: httpx.AsyncClient, token: str) -> None:
    print("2. the golden path drives through HTTP")
    r = await client.post(
        "/tasks", headers=auth(token), json={"title": "三角恒等式", "objective": "一节课"}
    )
    check(r.status_code == 201, f"task created (got {r.status_code})")
    body = r.json()
    task_id = body["id"]
    check(body["status"] == "draft", f"new task is draft (got {body['status']})")
    check(
        "/tasks/{task_id}/actions/submit-requirement" in body["allowed_actions"],
        "allowed_actions is populated from the contract",
    )

    r = await client.post(
        f"/tasks/{task_id}/actions/submit-requirement",
        headers=auth(token),
        json={"expected_state_version": 0},
    )
    check(r.status_code == 200, f"submit-requirement accepted (got {r.status_code})")
    check(r.json()["status"] == "planning", f"task moved to planning (got {r.json()['status']})")

    # stale version must be refused with the frozen code
    r = await client.post(
        f"/tasks/{task_id}/actions/approve-plan",
        headers=auth(token),
        json={"expected_state_version": 0},
    )
    check(r.status_code == 409, f"illegal/stale action refused (got {r.status_code})")
    check(r.json()["error"]["code"] == "STATE_CONFLICT", "refusal carries STATE_CONFLICT")

    # kebab-case route that has no trigger behind it
    r = await client.post(
        f"/tasks/{task_id}/actions/not-a-real-action",
        headers=auth(token),
        json={"expected_state_version": 1},
    )
    check(r.status_code == 404, f"unknown action is 404 (got {r.status_code})")


async def scenario_ownership(client: httpx.AsyncClient) -> None:
    print("3. one teacher cannot read another teacher's task")
    _, token_a = await make_user()
    _, token_b = await make_user()

    r = await client.post("/tasks", headers=auth(token_a), json={"title": "A 的任务"})
    task_id = r.json()["id"]

    r = await client.get(f"/tasks/{task_id}", headers=auth(token_b))
    check(r.status_code == 404, f"other teacher gets 404, not 403 (got {r.status_code})")
    check(
        r.json()["error"]["code"] == "NOT_FOUND",
        "existence is not leaked through the error code",
    )

    r = await client.get("/tasks", headers=auth(token_b))
    check(r.json()["items"] == [], "the list is empty for the other teacher")


async def scenario_validation(client: httpx.AsyncClient) -> None:
    print("4. payload validation is enforced at the boundary")
    _, token = await make_user()

    r = await client.post("/tasks", headers=auth(token), json={"title": ""})
    check(r.status_code == 422, f"empty title rejected (got {r.status_code})")

    r = await client.post("/tasks", headers=auth(token), json={})
    check(r.status_code == 422, f"missing title rejected (got {r.status_code})")

    r = await client.get("/healthz")
    check(r.status_code == 200 and r.json()["status"] == "ok", "healthz works without auth")


async def provision_runtime_role(url: str) -> str:
    """Create a non-superuser role and return a URL that connects as it.

    This is not ceremony. A superuser bypasses row-level security entirely, so
    testing the API as `postgres` silently disables tenant isolation — the very
    thing these tests claim to check. The application must never run as a
    superuser, so the test must not either.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    admin = create_async_engine(url)
    role = "chilon_api_test"
    password = "api_test_only"
    async with admin.begin() as conn:
        await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        await conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        )
    await admin.dispose()
    return url.replace("postgres:chilon_test_only@", f"{role}:{password}@")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    runtime_url = await provision_runtime_role(url)
    db.init(runtime_url)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            _, token = await scenario_auth(client)
            await scenario_task_flow(client, token)
            await scenario_ownership(client)
            await scenario_validation(client)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: HTTP layer honours the frozen surface, codes and tenant isolation")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
