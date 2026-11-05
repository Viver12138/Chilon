"""HTTP dependencies and error mapping.

**Authentication is a dependency, not an endpoint.** The frozen API surface (D5)
defines 64 endpoints and none of them is `/auth/*`, so this layer does not invent
one: a Bearer token is resolved against `user_sessions` and everything downstream
runs inside that teacher's RLS context. Login/registration live in the identity
service and will get their own contract revision if they are exposed over HTTP.

Every domain error maps to one of the 18 frozen error codes with its declared HTTP
status. Mapping is centralised so a new service cannot invent a 500 by forgetting
to translate something.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session as db
from app.services import executions, identity, plans, steps, tasks, tools


class ApiError(Exception):
    """Carries a frozen error code and the status declared for it."""

    def __init__(self, status: int, code: str, detail: str | None = None) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


# domain error -> (http status, frozen error code)
ERROR_MAP: list[tuple[type[BaseException], int, str]] = [
    (tasks.TaskNotFound, 404, "NOT_FOUND"),
    (plans.ApprovalNotFound, 404, "NOT_FOUND"),
    (plans.PlanVersionNotFound, 404, "NOT_FOUND"),
    (executions.ExecutionNotFound, 404, "NOT_FOUND"),
    (steps.StepNotFound, 404, "NOT_FOUND"),
    (tools.ToolNotFound, 404, "NOT_FOUND"),
    (tasks.IllegalTransition, 409, "STATE_CONFLICT"),
    (executions.IllegalExecutionTransition, 409, "STATE_CONFLICT"),
    (steps.StepConflict, 409, "STATE_CONFLICT"),
    (tools.ToolConflict, 409, "STATE_CONFLICT"),
    (tasks.StateConflict, 409, "STATE_CONFLICT"),
    (executions.ExecutionConflict, 409, "STATE_CONFLICT"),
    (plans.ApprovalNotConsumable, 409, "APPROVAL_CONSUMED"),
    (executions.StaleFence, 409, "WORKER_LEASE_LOST"),
    (executions.LeaseUnavailable, 409, "WORKER_LEASE_LOST"),
    (tools.ToolNotGranted, 403, "FORBIDDEN"),
    (tools.ToolApprovalRequired, 409, "PLAN_NOT_APPROVED"),
    (tools.ToolDisabled, 409, "CAPABILITY_GAP"),
    (steps.PlanDagError, 422, "AST_INVALID"),
    (identity.SessionInvalid, 401, "FORBIDDEN"),
    (identity.AccountNotActive, 403, "FORBIDDEN"),
]


def translate(exc: BaseException) -> ApiError | None:
    for exc_type, status, code in ERROR_MAP:
        if isinstance(exc, exc_type):
            return ApiError(status, code, str(exc))
    return None


def _response(status: int, code: str, detail: str | None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "detail": detail}})


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _response(exc.status, exc.code, exc.detail)


def install_error_handlers(app) -> None:
    """Register one handler per known exception type.

    A bare `Exception` handler does not work here: Starlette's server-error
    middleware *re-raises* after responding, so under an ASGI transport the caller
    sees the exception instead of the JSON body. Registering the concrete types
    makes them ordinary application errors, which is what they are.
    """
    from fastapi import FastAPI  # local import to avoid a cycle at module load

    assert isinstance(app, FastAPI)
    app.add_exception_handler(ApiError, api_error_handler)
    for exc_type, status, code in ERROR_MAP:

        def handler(request: Request, exc: BaseException, _s=status, _c=code) -> JSONResponse:
            return _response(_s, _c, str(exc))

        app.add_exception_handler(exc_type, handler)


async def error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiError):
        return _response(exc.status, exc.code, exc.detail)
    mapped = translate(exc)
    if mapped is not None:
        return _response(mapped.status, mapped.code, mapped.detail)
    return _response(500, "INTERNAL", str(exc))


# Routes an account may still use while it must change its password. Anything else is
# refused: a flag that only the UI respects is advice, not enforcement.
PASSWORD_CHANGE_ALLOWED = (
    "/auth/password",
    "/auth/me",
    "/auth/logout",
)


async def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "FORBIDDEN", "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    async with db.system_session() as session:
        try:
            user_id = await identity.authenticate(session, token)
        except identity.SessionInvalid as exc:
            raise ApiError(401, "FORBIDDEN", str(exc)) from exc
        if await identity.must_change_password(session, user_id):
            # the account is on a password an operator handed over; only the route that
            # lets it choose its own is allowed through
            if request.url.path not in PASSWORD_CHANGE_ALLOWED:
                raise ApiError(
                    403,
                    "FORBIDDEN",
                    "this account must change its password first (POST /auth/password)",
                )
    return user_id


async def user_session(
    user_id: Annotated[uuid.UUID, Depends(current_user)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request, with the RLS context already set."""
    async with db.session_for(user_id) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(user_session)]
UserDep = Annotated[uuid.UUID, Depends(current_user)]
