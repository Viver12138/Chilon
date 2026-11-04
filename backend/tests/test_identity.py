"""Identity service tests.

Each assertion covers a way authentication can fail silently rather than loudly:
a plaintext password in the database, an offline-storable session token, a login
that reveals whether a username exists, a revoked session that still works.

Run against a disposable database:
    CHILON_TEST_DATABASE_URL=postgresql+psycopg://... python backend/tests/test_identity.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402
from app.services import identity  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def scenario_register(uid_holder: dict) -> None:
    print("1. register: creates identity and credentials, stores no plaintext")
    username = f"t_{uuid.uuid4().hex[:10]}"
    password = "correct horse battery staple"

    async with db.system_session() as s:
        user_id = await identity.register(s, username, password, display_name="Test Teacher")
    uid_holder["user_id"] = user_id
    uid_holder["username"] = username
    uid_holder["password"] = password

    async with db.system_session() as s:
        row = (
            await s.execute(
                text(
                    """
                    SELECT u.username, u.status, c.password_hash, c.algorithm
                    FROM users u JOIN user_credentials c ON c.user_id = u.id
                    WHERE u.id = :id
                    """
                ),
                {"id": user_id},
            )
        ).one()

    check(row.username == username, "username stored normalised")
    check(row.status == "active", "account starts active")
    check(password not in row.password_hash, "password does not appear in the stored hash")
    check(row.password_hash.startswith("scrypt$"), "hash carries its KDF parameters")
    check(row.algorithm == "scrypt", "algorithm column records the real KDF")

    # the schema enforces lowercase usernames; the service must not rely on luck
    async with db.system_session() as s:
        await identity.register(s, f"UP_{uuid.uuid4().hex[:6]}", "pw123456")
        stored = (
            await s.execute(
                text("SELECT username FROM users WHERE username LIKE 'up\\_%' ORDER BY created_at DESC")
            )
        ).scalar_one()
    check(stored == stored.lower(), "uppercase input is normalised before insert")


async def scenario_duplicate(uid_holder: dict) -> None:
    print("2. duplicate username is rejected")
    async with db.system_session() as s:
        try:
            await identity.register(s, uid_holder["username"], "another password")
            check(False, "duplicate username was accepted")
        except identity.UsernameTaken:
            check(True, "duplicate username rejected")


async def scenario_login(uid_holder: dict) -> None:
    print("3. login: correct password issues a session, wrong password does not")
    async with db.system_session() as s:
        sess = await identity.login(s, uid_holder["username"], uid_holder["password"])
    uid_holder["token"] = sess.token
    check(sess.user_id == uid_holder["user_id"], "session belongs to the user")
    check(len(sess.token) > 30, "token has real entropy")

    async with db.system_session() as s:
        stored = (
            await s.execute(
                text("SELECT token_hash FROM user_sessions WHERE id = :id"), {"id": sess.session_id}
            )
        ).scalar_one()
    check(stored != sess.token, "session token is not stored in plaintext")
    check(len(stored) == 64, "token stored as sha256 hex")

    async with db.system_session() as s:
        try:
            await identity.login(s, uid_holder["username"], "wrong password")
            check(False, "wrong password was accepted")
        except identity.InvalidCredentials:
            check(True, "wrong password rejected")

    # unknown user must fail the same way as a wrong password
    async with db.system_session() as s:
        try:
            await identity.login(s, f"nobody_{uuid.uuid4().hex[:6]}", "whatever")
            check(False, "unknown user was accepted")
        except identity.InvalidCredentials as exc:
            check(
                type(exc) is identity.InvalidCredentials,
                "unknown user and wrong password raise the same error type",
            )


async def scenario_authenticate(uid_holder: dict) -> None:
    print("4. authenticate: resolves the token, rejects expiry and revocation")
    async with db.system_session() as s:
        resolved = await identity.authenticate(s, uid_holder["token"])
    check(resolved == uid_holder["user_id"], "token resolves to the right user")

    async with db.system_session() as s:
        try:
            await identity.authenticate(s, "not-a-real-token")
            check(False, "bogus token was accepted")
        except identity.SessionInvalid:
            check(True, "bogus token rejected")

    # expiry is evaluated against the supplied clock, not the process clock
    async with db.system_session() as s:
        try:
            await identity.authenticate(
                s, uid_holder["token"], now=datetime.now(timezone.utc) + identity.SESSION_TTL + timedelta(seconds=1)
            )
            check(False, "expired session was accepted")
        except identity.SessionInvalid:
            check(True, "expired session rejected")

    async with db.system_session() as s:
        await identity.logout(s, uid_holder["token"])
    async with db.system_session() as s:
        try:
            await identity.authenticate(s, uid_holder["token"])
            check(False, "revoked session was still accepted")
        except identity.SessionInvalid:
            check(True, "revoked session rejected")


async def scenario_closed_account(uid_holder: dict) -> None:
    print("5. closed account cannot log in and cannot keep a session")
    username = f"closed_{uuid.uuid4().hex[:8]}"
    async with db.system_session() as s:
        user_id = await identity.register(s, username, "pw12345678")
    async with db.system_session() as s:
        sess = await identity.login(s, username, "pw12345678")
    async with db.system_session() as s:
        await s.execute(
            text("UPDATE users SET status = 'closed', closed_at = now() WHERE id = :id"),
            {"id": user_id},
        )

    async with db.system_session() as s:
        try:
            await identity.login(s, username, "pw12345678")
            check(False, "closed account logged in")
        except identity.AccountNotActive:
            check(True, "closed account cannot log in")

    async with db.system_session() as s:
        try:
            await identity.authenticate(s, sess.token)
            check(False, "closed account kept a live session")
        except identity.AccountNotActive:
            check(True, "existing session of a closed account is refused")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    holder: dict = {}
    try:
        await scenario_register(holder)
        await scenario_duplicate(holder)
        await scenario_login(holder)
        await scenario_authenticate(holder)
        await scenario_closed_account(holder)
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: identity service refuses the failure modes that matter")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
