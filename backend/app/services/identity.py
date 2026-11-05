"""Identity service: registration, login, sessions.

Decisions worth knowing before reading the code:

* **Password hashing uses scrypt from the standard library**, not Argon2id.
  The schema's `algorithm` column defaults to `argon2id`, and we store `scrypt`
  explicitly. Argon2id is the preferred choice; it needs a third-party package,
  and swapping it in is a one-line change once that dependency is vendored.
  What matters now is that the stored value is a one-way KDF output, never a
  plaintext or a reversible encoding.

* **Session tokens are stored as SHA-256 hashes.** The plaintext token exists
  only in the login response. A database leak therefore does not hand over live
  sessions.

* **The `users` / `user_credentials` / `user_sessions` tables are service-scoped,
  not per-tenant.** Authentication has to find a user by username *before* any
  user context exists, so row-level security cannot express it; the service is
  the authorization boundary for these three tables. This is recorded as an
  explicit exception rather than hidden.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32
SESSION_TTL = timedelta(days=7)


class IdentityError(Exception):
    """Base class so callers can map one error family to HTTP status codes."""


class UsernameTaken(IdentityError):
    pass


class InvalidCredentials(IdentityError):
    pass


class AccountNotActive(IdentityError):
    pass


class SessionInvalid(IdentityError):
    pass


@dataclass(frozen=True)
class Session:
    token: str
    session_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    must_change_password: bool = False


def hash_password(password: str) -> str:
    """Return `scrypt$n$r$p$salt$hash` so parameters travel with the hash."""
    if not password:
        raise IdentityError("password must not be empty")
    salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_username(username: str) -> str:
    """Usernames are stored lowercase; the schema enforces `username = lower(username)`."""
    return username.strip().lower()


async def register(
    session: AsyncSession,
    username: str,
    password: str,
    display_name: str | None = None,
) -> uuid.UUID:
    username = normalise_username(username)
    if not username:
        raise IdentityError("username must not be empty")

    taken = (
        await session.execute(text("SELECT 1 FROM users WHERE username = :u"), {"u": username})
    ).first()
    if taken:
        raise UsernameTaken(username)

    user_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO users (id, username, display_name)
            VALUES (:id, :username, :display_name)
            """
        ),
        {"id": user_id, "username": username, "display_name": display_name or username},
    )
    await session.execute(
        text(
            """
            INSERT INTO user_credentials (id, user_id, password_hash, algorithm)
            VALUES (gen_random_uuid(), :user_id, :hash, 'scrypt')
            """
        ),
        {"user_id": user_id, "hash": hash_password(password)},
    )
    return user_id


async def login(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    now: datetime | None = None,
) -> Session:
    username = normalise_username(username)
    row = (
        await session.execute(
            text(
                """
                SELECT u.id, u.status, c.password_hash,
                       COALESCE(c.must_change_password, false) AS must_change_password
                FROM users u
                JOIN user_credentials c ON c.user_id = u.id
                WHERE u.username = :username
                """
            ),
            {"username": username},
        )
    ).first()

    # Same error for "no such user" and "wrong password": never confirm which.
    if row is None or not verify_password(password, row.password_hash):
        raise InvalidCredentials(username)
    if row.status != "active":
        raise AccountNotActive(row.status)

    token = secrets.token_urlsafe(32)
    expires_at = (now or datetime.now(timezone.utc)) + SESSION_TTL
    session_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO user_sessions
                (id, user_id, token_hash, expires_at, user_agent, ip_address)
            VALUES
                (:id, :user_id, :token_hash, :expires_at, :user_agent, :ip)
            """
        ),
        {
            "id": session_id,
            "user_id": row.id,
            "token_hash": token_hash(token),
            "expires_at": expires_at,
            "user_agent": user_agent,
            "ip": ip_address,
        },
    )
    await session.execute(
        text("UPDATE users SET last_login_at = now() WHERE id = :id"), {"id": row.id}
    )
    return Session(
        token=token,
        session_id=session_id,
        user_id=row.id,
        expires_at=expires_at,
        must_change_password=bool(row.must_change_password),
    )


async def authenticate(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> uuid.UUID:
    """Resolve a session token to a user id, rejecting expired and revoked ones."""
    row = (
        await session.execute(
            text(
                """
                SELECT s.user_id, s.expires_at, s.revoked_at, u.status
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = :th
                """
            ),
            {"th": token_hash(token)},
        )
    ).first()

    if row is None or row.revoked_at is not None:
        raise SessionInvalid("unknown or revoked session")
    current = now or datetime.now(timezone.utc)
    if row.expires_at <= current:
        raise SessionInvalid("expired session")
    if row.status != "active":
        raise AccountNotActive(row.status)
    return row.user_id


async def logout(session: AsyncSession, token: str) -> None:
    await session.execute(
        text("UPDATE user_sessions SET revoked_at = now() WHERE token_hash = :th AND revoked_at IS NULL"),
        {"th": token_hash(token)},
    )


async def must_change_password(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Whether the account is still using a password an operator handed over."""
    value = (
        await session.execute(
            text("SELECT must_change_password FROM user_credentials WHERE user_id = :u"),
            {"u": user_id},
        )
    ).scalar()
    return bool(value)
