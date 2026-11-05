"""Authentication endpoints.

**These four routes are not in D5.** The frozen surface has 64 endpoints and no
`/auth/*`, which makes the product unusable: a teacher has no way to obtain the
first token. They are added here and flagged as a contract gap rather than smuggled
into an existing route.

A consequence worth naming: there is no frozen error code for "username taken", so
this module introduces `USERNAME_TAKEN`. Inventing one code, in one place, with the
gap written down, is better than misusing `STATE_CONFLICT` to mean something it does
not.

Authentication runs on `system_session()` — no user context exists yet, which is
exactly why the identity tables are service-scoped (see D.34).
"""

from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.api.deps import ApiError, UserDep, current_user
from app.db import session as db
from app.services import agent as agent_service
from app.services import identity, passwords

router = APIRouter(tags=["auth"], prefix="/auth")

MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


@router.post("/register", status_code=201)
async def register(payload: RegisterRequest) -> dict:
    async with db.system_session() as session:
        try:
            user_id = await identity.register(
                session, payload.username, payload.password, payload.display_name
            )
        except identity.UsernameTaken:
            # not one of the 18 frozen codes; documented as a gap in this module's
            # docstring so it is not mistaken for a contract-defined error
            raise ApiError(409, "USERNAME_TAKEN", f"username {payload.username!r} is taken")
        except identity.IdentityError as exc:
            raise ApiError(422, "AST_INVALID", str(exc)) from exc
    # a brand new teacher owns no tools yet; grants are owner-scoped, so they are
    # written in that teacher's own context rather than the registration session
    async with db.session_for(user_id) as session:
        await agent_service.ensure_default_grants(session, user_id)
    return {"user_id": str(user_id), "username": payload.username.strip().lower()}


@router.post("/login")
async def login(payload: LoginRequest) -> dict:
    async with db.system_session() as session:
        try:
            issued = await identity.login(session, payload.username, payload.password)
        except identity.AccountNotActive as exc:
            raise ApiError(403, "FORBIDDEN", str(exc)) from exc
        except identity.IdentityError:
            # same answer for "no such user" and "wrong password": an attacker must
            # not be able to enumerate usernames through this endpoint
            raise ApiError(401, "FORBIDDEN", "invalid credentials")
    return {
        "token": issued.token,
        "expires_at": issued.expires_at.isoformat(),
        "user_id": str(issued.user_id),
        "must_change_password": issued.must_change_password,
    }


@router.post("/logout", status_code=204)
async def logout(authorization: Annotated[str | None, Header()] = None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "FORBIDDEN", "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    async with db.system_session() as session:
        await identity.logout(session, token)


@router.get("/me")
async def me(user: UserDep) -> dict:
    async with db.session_for(user) as session:
        from sqlalchemy import text

        row = (
            await session.execute(
                text("SELECT id, username, display_name, is_admin, status FROM users WHERE id = :id"),
                {"id": user},
            )
        ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "user not found")
    return {
        "user_id": str(row.id),
        "username": row.username,
        "display_name": row.display_name,
        "is_admin": row.is_admin,
        "status": row.status,
    }


class ResetRequest(BaseModel):
    new_password: str | None = Field(default=None, min_length=8, max_length=200)


@router.post("/users/{user_id}/password-reset")
async def reset_password(
    user_id: uuid.UUID, payload: ResetRequest, requester: UserDep
) -> dict:
    """Reset another account's password. Admin only.

    Not self-service on purpose: without an email channel there is no way to verify
    that the caller owns the account, so offering one would be an account takeover
    with extra steps. The operator path is `tools/reset_password.py`.
    """
    async with db.system_session() as session:
        requester_row = (
            await session.execute(
                text("SELECT is_admin, status FROM users WHERE id = :id"), {"id": requester}
            )
        ).first()
    if requester_row is None or not requester_row.is_admin:
        raise ApiError(403, "FORBIDDEN", "administrator rights required")
    if requester_row.status != "active":
        raise ApiError(403, "FORBIDDEN", "administrator account is not active")

    new_password = payload.new_password or secrets.token_urlsafe(12)
    async with db.system_session() as session:
        try:
            revoked = await passwords.set_password(session, user_id, new_password)
        except passwords.ResetNotAllowed as exc:
            raise ApiError(404, "NOT_FOUND", str(exc)) from exc
    return {
        "user_id": str(user_id),
        "password": None if payload.new_password else new_password,
        "sessions_revoked": revoked,
    }


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password")
async def change_password(
    payload: ChangePasswordRequest,
    requester: UserDep,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Change your own password, keeping the session you are using.

    The counterpart of the admin reset: this is the path for "I know my password and
    want a different one". Every other session is revoked.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "FORBIDDEN", "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    async with db.session_for(requester) as session:
        try:
            revoked = await passwords.change_own(
                session, requester, payload.current_password, payload.new_password, token=token
            )
        except identity.InvalidCredentials:
            raise ApiError(401, "FORBIDDEN", "current password is incorrect")
        except passwords.ResetNotAllowed as exc:
            raise ApiError(422, "AST_INVALID", str(exc)) from exc
    return {"sessions_revoked": revoked}
