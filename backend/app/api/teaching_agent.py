"""HTTP surface for the Chilon Teaching Agent.

Tools use the same PostgreSQL/Qdrant data as the teacher UI; the agent never reads
the database directly. `POST /chat` is a thin orchestration over those tools.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.api.deps import ApiError, UserDep
from app.db import session as db
from app.services import teaching_agent

router = APIRouter(prefix='/teaching-agent', tags=['teaching-agent'])


class SearchKnowledgeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)
    source_types: list[str] | None = None
    year_range: dict[str, int] | None = None
    question_types: list[str] | None = None
    knowledge_points: list[str] | None = None
    mode: str = Field(default='h', pattern='^(h|hr|auto)$')
    scope_override: str | None = Field(default=None, pattern='^(knowledge|question)$')


class TextbookRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    grade: str | None = None
    volume: str | None = None
    limit: int = Field(default=8, ge=1, le=20)


class CalculateRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=500)


class ChatTurn(BaseModel):
    role: str = Field(pattern='^(user|assistant)$')
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list)


@router.post('/tools/search_knowledge')
async def search_knowledge(payload: SearchKnowledgeRequest, _: UserDep) -> dict:
    try:
        return await run_in_threadpool(
            teaching_agent.search_knowledge,
            payload.query,
            limit=payload.limit,
            source_types=payload.source_types,
            year_range=payload.year_range,
            question_types=payload.question_types,
            knowledge_points=payload.knowledge_points,
            mode=payload.mode,
            scope_override=payload.scope_override,
        )
    except Exception as exc:  # noqa: BLE001 - tool envelope owns the error
        raise ApiError(500, 'INTERNAL', f'search_knowledge failed: {exc}') from exc


@router.post('/tools/get_textbook_content')
async def get_textbook_content(payload: TextbookRequest, _: UserDep) -> dict:
    try:
        return await run_in_threadpool(
            teaching_agent.textbook_content,
            payload.query, grade=payload.grade, volume=payload.volume, limit=payload.limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise ApiError(500, 'INTERNAL', f'get_textbook_content failed: {exc}') from exc


@router.get('/tools/questions/{question_id}')
async def get_question_detail(question_id: uuid.UUID, user: UserDep) -> dict:
    async with db.session_for(user) as session:
        return await teaching_agent.get_question_detail(session, str(question_id))


@router.get('/tools/sources/{source_id}')
async def get_source_detail(source_id: uuid.UUID, user: UserDep) -> dict:
    async with db.session_for(user) as session:
        return await teaching_agent.get_source_detail(session, str(source_id))


@router.post('/tools/calculate_math')
async def calculate_math(payload: CalculateRequest, _: UserDep) -> dict:
    return teaching_agent.calculate_math(payload.expression)


@router.post('/chat')
async def chat(payload: ChatRequest, user: UserDep) -> dict:
    try:
        async with db.session_for(user) as session:
            result = await teaching_agent.chat(
                session, user, payload.message,
                history=[turn.model_dump() for turn in payload.history],
            )
        return result
    except Exception as exc:  # noqa: BLE001 - keep the agent usable and explicit
        raise ApiError(500, 'INTERNAL', f'teaching agent failed: {exc}') from exc


@router.get('/manifest')
async def manifest(_: UserDep) -> dict:
    """What the agent loads; useful for debugging Prompt/Skill wiring."""
    return {
        'name': 'Chilon Teaching Agent',
        'version': '1.0',
        'tools': ['search_knowledge', 'get_question_detail', 'get_textbook_content',
                  'get_source_detail', 'calculate_math'],
        'skills': ['knowledge-summary', 'question-retrieval', 'question-analysis',
                   'lesson-planning', 'exam-analysis', 'teaching-material-generation'],
        'chat_model': 'qwen-plus',
    }
