"""Retrieval-router gray API.

Phase 1: return the routing decision, not hits. The caller keeps using the H path
(or the existing product search) and can log the returned mode for an A/B.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ApiError, UserDep
from app.services import retrieval_router

router = APIRouter(tags=["retrieval"], prefix="/retrieval")


class RouteRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@router.post("/route")
async def route(payload: RouteRequest, user: UserDep) -> dict:
    try:
        return retrieval_router.decide(payload.query, user_key=str(user.id))
    except ValueError as exc:
        raise ApiError(422, "AST_INVALID", str(exc)) from exc


@router.get("/router")
async def router_status(user: UserDep) -> dict:
    from app import settings

    return {
        "flag": settings.get("CHILON_RETRIEVAL_ROUTER", "off"),
        "percent": int(settings.get("CHILON_RETRIEVAL_ROUTER_PERCENT", "100") or 100),
        "policy": "H default; HR for formula/knowledge/comparison queries",
    }
