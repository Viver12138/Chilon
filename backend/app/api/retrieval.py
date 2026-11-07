"""Retrieval-router gray API.

Phase 1: return the routing decision, not hits. The caller keeps using the H path
(or the existing product search) and can log the returned mode for an A/B.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import ApiError, UserDep
from app.services import retrieval_router, routed_retrieval

router = APIRouter(tags=["retrieval"], prefix="/retrieval")


class RouteRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)
    mode: str = Field(default='auto', pattern='^(auto|h|hr)$')


@router.post("/search")
async def search(payload: SearchRequest, user: UserDep) -> dict:
    try:
        return await run_in_threadpool(
            routed_retrieval.search,
            payload.query,
            limit=payload.limit,
            mode=payload.mode,
            user_key=str(user),
        )
    except RuntimeError as exc:
        raise ApiError(503, 'CAPABILITY_GAP', str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError(500, 'INTERNAL', f'retrieval failed: {exc}') from exc


@router.post("/route")
async def route(payload: RouteRequest, user: UserDep) -> dict:
    try:
        return retrieval_router.decide(payload.query, user_key=str(user))
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
