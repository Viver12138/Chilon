"""Password reset tests.

The property that makes a reset a reset: **every existing session dies.** A reset that
leaves old tokens alive is worse than no reset, because the usual reason to reset is
that someone else may already have the account.

Runs as the application role; the admin guard is checked against the `users` table,
so a reset attempt from a non-admin must fail before any credential is touched.
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
from app.services import identity, passwords  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        async with db.system_session() as session:
            admin_name = f"adm_{uuid.uuid4().hex[:8]}"
            admin = await identity.register(session, admin_name, "admin_password_1")
            teacher_name = f"tea_{uuid.uuid4().hex[:8]}"
            teacher = await identity.register(session, teacher_name, "teacher_password_1")

            # making someone an administrator is an administrative act, not an API call
            await session.execute(
                text("UPDATE users SET is_admin = true WHERE id = :id"), {"id": admin}
            )
            admin_login = await identity.login(session, admin_name, "admin_password_1")
            teacher_login = await identity.login(session, teacher_name, "teacher_password_1")

        admin_headers = {"Authorization": f"Bearer {admin_login.token}"}
        teacher_headers = {"Authorization": f"Bearer {teacher_login.token}"}

        print("1. a non-admin cannot reset anyone")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/auth/users/{teacher}/password-reset",
                headers=teacher_headers,
                json={"new_password": "hijacked_password"},
            )
        check(r.status_code == 403, f"non-admin refused (got {r.status_code})")

        print("2. an admin can reset, and every session dies with it")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/auth/users/{teacher}/password-reset",
                headers=admin_headers,
                json={"new_password": "brand_new_password"},
            )
        check(r.status_code == 200, f"admin reset accepted (got {r.status_code}: {r.text[:120]})")
        body = r.json()
        check(body["sessions_revoked"] >= 1, f"sessions revoked (got {body['sessions_revoked']})")

        print("3. the old session and the old password are both dead")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/auth/me", headers=teacher_headers)
            check(r.status_code == 401, f"the revoked token is refused (got {r.status_code})")
            r = await client.post(
                "/auth/login", json={"username": teacher_name, "password": "teacher_password_1"}
            )
            check(r.status_code == 401, f"the old password is refused (got {r.status_code})")
            r = await client.post(
                "/auth/login", json={"username": teacher_name, "password": "brand_new_password"}
            )
            check(r.status_code == 200, f"the new password works (got {r.status_code})")
            new_token = r.json()["token"]
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
            check(r.status_code == 200, "and it opens the API")

        print("4. a short password is refused, and nothing is changed")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/auth/users/{teacher}/password-reset",
                headers=admin_headers,
                json={"new_password": "short"},
            )
        check(r.status_code == 422, f"short password refused (got {r.status_code})")

        print("5. the operator path generates a password when none is given")
        async with db.system_session() as session:
            generated, note = await passwords.reset_for_username(session, teacher_name)
        check(len(generated) >= 12, f"generated password has entropy ({len(generated)} chars)")
        check("revoked" in note, f"the note reports session revocation ({note})")
        async with db.system_session() as session:
            issued = await identity.login(session, teacher_name, generated)
        check(issued.user_id == teacher, "the generated password logs in")

        print("6. an unknown username is refused, not silently ignored")
        async with db.system_session() as session:
            try:
                await passwords.reset_for_username(session, "nobody_at_all")
                check(False, "an unknown user was accepted")
            except passwords.ResetNotAllowed:
                check(True, "an unknown user is refused")


        print("7. changing your own password keeps this session and kills the others")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/auth/login", json={"username": teacher_name, "password": generated}
            )
            live_token = r.json()["token"]
            live_headers = {"Authorization": f"Bearer {live_token}"}
            other = await client.post(
                "/auth/login", json={"username": teacher_name, "password": generated}
            )
            other_headers = {"Authorization": f"Bearer {other.json()['token']}"}

            r = await client.post(
                "/auth/password",
                headers=live_headers,
                json={"current_password": "wrong_one", "new_password": "another_password_1"},
            )
            check(r.status_code == 401, f"a wrong current password is refused (got {r.status_code})")

            r = await client.post(
                "/auth/password",
                headers=live_headers,
                json={"current_password": generated, "new_password": "another_password_1"},
            )
            check(r.status_code == 200, f"change accepted (got {r.status_code}: {r.text[:120]})")
            check(r.json()["sessions_revoked"] >= 1, "the other session was revoked")

            r = await client.get("/auth/me", headers=live_headers)
            check(r.status_code == 200, f"this session survives (got {r.status_code})")
            r = await client.get("/auth/me", headers=other_headers)
            check(r.status_code == 401, f"the other session is dead (got {r.status_code})")
            r = await client.post(
                "/auth/login", json={"username": teacher_name, "password": "another_password_1"}
            )
            check(r.status_code == 200, "and the new password logs in")


        print("8. an operator-set password must be changed before the account works")
        async with db.system_session() as session:
            temp_password, _ = await passwords.reset_for_username(session, teacher_name)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/auth/login", json={"username": teacher_name, "password": temp_password}
            )
            check(r.status_code == 200, f"the temporary password logs in (got {r.status_code})")
            check(
                r.json().get("must_change_password") is True,
                f"login says a change is required (got {r.json().get('must_change_password')})",
            )
            temp_headers = {"Authorization": f"Bearer {r.json()['token']}"}

            r = await client.get("/tasks", headers=temp_headers)
            check(r.status_code == 403, f"normal API use is refused (got {r.status_code})")
            check(
                "change its password" in r.text,
                "the refusal explains what to do",
            )
            r = await client.get("/auth/me", headers=temp_headers)
            check(r.status_code == 200, "but /auth/me still works")

            r = await client.post(
                "/auth/password",
                headers=temp_headers,
                json={"current_password": temp_password, "new_password": "chosen_by_teacher_1"},
            )
            check(r.status_code == 200, f"the teacher can set their own password (got {r.status_code})")

            r = await client.get("/tasks", headers=temp_headers)
            check(r.status_code == 200, f"and the account works again (got {r.status_code})")

            r = await client.post(
                "/auth/login",
                json={"username": teacher_name, "password": "chosen_by_teacher_1"},
            )
            check(r.status_code == 200, "the new password logs in")
            check(
                r.json().get("must_change_password") is False,
                "and the flag is cleared",
            )


        print("9. the web UI is closed too, and its own form clears the flag")
        async with db.system_session() as session:
            page_password, _ = await passwords.reset_for_username(session, teacher_name)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/ui/login",
                data={"username": teacher_name, "password": page_password},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"UI login accepted (got {r.status_code})")
            r = await client.get("/ui/tasks", follow_redirects=False)
            check(r.status_code == 303, f"the task page redirects (got {r.status_code})")
            check(
                r.headers.get("location") == "/ui/password",
                f"and it redirects to the password page (got {r.headers.get('location')})",
            )
            r = await client.get("/ui/password")
            check(r.status_code == 200 and "临时密码" in r.text, "the page explains why")
            r = await client.post(
                "/ui/password",
                data={"current_password": page_password, "new_password": "chosen_in_browser_1"},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"the form accepts the change (got {r.status_code})")
            r = await client.get("/ui/tasks")
            check(r.status_code == 200, f"the task page opens again (got {r.status_code})")

        # The token issued before the last change must be dead, whoever else is live.
        # A raw "how many sessions are open" count would depend on how many logins the
        # earlier scenarios happened to make, and would pass or fail for the wrong
        # reason.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(
                "/auth/me", headers={"Authorization": f"Bearer {issued.token}"}
            )
        check(r.status_code == 401, f"a pre-change token is dead (got {r.status_code})")
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: reset is admin-only and kills every existing session")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
