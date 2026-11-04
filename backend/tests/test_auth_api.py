"""Authentication tests, run as a non-superuser role.

The last time these tests ran as `postgres`, row-level security was silently off and
a cross-tenant read returned 200. Auth endpoints are the entry point for everything
else, so they are tested under the same conditions production will have.
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
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def provision_role(url: str) -> str:
    admin = create_async_engine(url)
    role, password = "chilon_auth_test", "auth_test_only"
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

    db.init(await provision_role(url))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            username = f"auth_{uuid.uuid4().hex[:8]}"
            password = "correct horse battery"

            print("1. a teacher can register and log in")
            r = await client.post(
                "/auth/register",
                json={"username": username, "password": password, "display_name": "张老师"},
            )
            check(r.status_code == 201, f"register succeeds (got {r.status_code}: {r.text[:100]})")
            user_id = r.json()["user_id"]

            r = await client.post("/auth/login", json={"username": username, "password": password})
            check(r.status_code == 200, f"login succeeds (got {r.status_code})")
            body = r.json()
            token = body["token"]
            check(len(token) > 30, "token has real entropy")
            check(body["user_id"] == user_id, "login returns the same user")

            print("2. the token actually opens the rest of the API")
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            check(r.status_code == 200, f"/auth/me works (got {r.status_code})")
            check(r.json()["username"] == username.lower(), "username is normalised")
            check(r.json()["display_name"] == "张老师", "display name is kept")

            r = await client.get("/tasks", headers={"Authorization": f"Bearer {token}"})
            check(r.status_code == 200, "the same token can list tasks")

            r = await client.post(
                "/tasks", headers={"Authorization": f"Bearer {token}"}, json={"title": "认证后建的任务"}
            )
            check(r.status_code == 201, "and create one")

            print("3. registration refuses what it should")
            r = await client.post("/auth/register", json={"username": username, "password": password})
            check(r.status_code == 409, f"duplicate username refused (got {r.status_code})")
            check(r.json()["error"]["code"] == "USERNAME_TAKEN", "with the documented gap code")

            r = await client.post("/auth/register", json={"username": "a", "password": password})
            check(r.status_code == 422, f"too-short username refused (got {r.status_code})")

            r = await client.post("/auth/register", json={"username": f"x{uuid.uuid4().hex[:6]}", "password": "short"})
            check(r.status_code == 422, f"too-short password refused (got {r.status_code})")

            print("4. login does not reveal whether a username exists")
            r = await client.post("/auth/login", json={"username": username, "password": "wrong password!"})
            wrong_pw = (r.status_code, r.json()["error"]["code"], r.json()["error"]["detail"])
            r = await client.post("/auth/login", json={"username": f"nobody_{uuid.uuid4().hex[:6]}", "password": "whatever1"})
            unknown = (r.status_code, r.json()["error"]["code"], r.json()["error"]["detail"])
            check(wrong_pw == unknown, f"identical answers for both cases ({wrong_pw[0]})")
            check(wrong_pw[0] == 401, "and it is a 401")

            print("5. logout revokes the token immediately")
            r = await client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
            check(r.status_code == 204, f"logout accepted (got {r.status_code})")
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            check(r.status_code == 401, f"the revoked token no longer works (got {r.status_code})")

            print("6. nothing sensitive is stored in the clear")
            async with db.system_session() as s:
                rows = (
                    await s.execute(
                        text(
                            """
                            SELECT c.password_hash, c.algorithm,
                                   (SELECT count(*) FROM user_sessions us
                                    WHERE us.user_id = u.id AND us.token_hash = :token) AS plaintext_tokens
                            FROM users u JOIN user_credentials c ON c.user_id = u.id
                            WHERE u.id = :id
                            """
                        ),
                        {"id": uuid.UUID(user_id), "token": token},
                    )
                ).one()
            check(password not in rows.password_hash, "password is not stored in the clear")
            check(rows.password_hash.startswith("scrypt$"), "hash carries its KDF parameters")
            check(rows.algorithm == "scrypt", "the algorithm column records the real KDF")
            check(rows.plaintext_tokens == 0, "no row stores the token in plaintext")
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: a teacher can get a token, use it, and lose it on logout")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
