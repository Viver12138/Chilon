"""Password reset and self-service change, using the columns the schema declares."""

from __future__ import annotations

import secrets

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import identity


class ResetNotAllowed(identity.IdentityError):
    pass


async def set_password(
    session: AsyncSession,
    user_id,
    new_password: str,
    *,
    revoke_sessions: bool = True,
    must_change: bool = True,
) -> int:
    """Replace the password, clear the lockout, and revoke sessions.

    Clearing `failed_attempts` / `locked_until` is part of the job: the reason someone
    resets is usually a forgotten password, and a forgotten password is usually
    preceded by several failed attempts. A reset that leaves the account locked has
    not recovered anything.
    """
    if len(new_password) < 8:
        raise ResetNotAllowed("password must be at least 8 characters")

    updated = (
        await session.execute(
            text(
                """
                UPDATE user_credentials
                SET password_hash = :hash,
                    algorithm = 'scrypt',
                    password_changed_at = now(),
                    failed_attempts = 0,
                    locked_until = NULL,
                    must_change_password = :must_change
                WHERE user_id = :user
                RETURNING id
                """
            ),
            {
                "hash": identity.hash_password(new_password),
                "user": user_id,
                "must_change": must_change,
            },
        )
    ).first()
    if updated is None:
        raise ResetNotAllowed("user has no credential record")

    if not revoke_sessions:
        return 0
    return await revoke_all_sessions(session, user_id)


async def revoke_all_sessions(
    session: AsyncSession, user_id, *, except_token_hash: str | None = None
) -> int:
    # the clause is built rather than paramterised with NULL: Postgres cannot infer the
    # type of `$n IS NULL`, and a cast would only hide that the branch does not apply
    keep_clause = "AND token_hash <> :keep" if except_token_hash else ""
    params: dict[str, object] = {"user": user_id}
    if except_token_hash:
        params["keep"] = except_token_hash
    result = await session.execute(
        text(
            f"""
            UPDATE user_sessions SET revoked_at = now()
            WHERE user_id = :user AND revoked_at IS NULL {keep_clause}
            """
        ),
        params,
    )
    return result.rowcount or 0


async def change_own(
    session: AsyncSession, user_id, current_password: str, new_password: str, *, token: str
) -> int:
    """Change your own password, keeping the session you are using.

    The current session survives because the caller proved they know both the old
    password and the live token; every *other* session is revoked, which is the point
    of changing a password you suspect is known elsewhere.
    """
    row = (
        await session.execute(
            text("SELECT password_hash FROM user_credentials WHERE user_id = :user"),
            {"user": user_id},
        )
    ).first()
    if row is None:
        raise ResetNotAllowed("user has no credential record")
    if not identity.verify_password(current_password, row.password_hash):
        raise identity.InvalidCredentials("current password is wrong")

    updated = (
        await session.execute(
            text(
                """
                UPDATE user_credentials
                SET password_hash = :hash, algorithm = 'scrypt',
                    password_changed_at = now(), failed_attempts = 0, locked_until = NULL,
                    must_change_password = false
                WHERE user_id = :user
                RETURNING id
                """
            ),
            {"hash": identity.hash_password(new_password), "user": user_id},
        )
    ).first()
    if updated is None:
        raise ResetNotAllowed("user has no credential record")

    return await revoke_all_sessions(
        session, user_id, except_token_hash=identity.token_hash(token)
    )


async def reset_for_username(
    session: AsyncSession, username: str, new_password: str | None = None
) -> tuple[str, str]:
    """Operator entry point: reset by username, generating a password when omitted."""
    row = (
        await session.execute(
            text("SELECT id FROM users WHERE username = :u"),
            {"u": identity.normalise_username(username)},
        )
    ).first()
    if row is None:
        raise ResetNotAllowed(f"no such user: {username}")

    password = new_password or secrets.token_urlsafe(12)
    revoked = await set_password(session, row.id, password)
    return password, f"{revoked} session(s) revoked"
