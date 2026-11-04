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

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.api.deps import ApiError, UserDep, current_user
from app.db import session as db
from app.services import agent as agent_service
from app.services import identity

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
