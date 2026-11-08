"""Stdio MCP bridge exposing Chilon's teaching tools to DeepSeek Harness.

Start (DSH preset does this automatically):

    python agent/mcp_server.py

Environment: CHILON_DATABASE_URL, QDRANT_URL, CHILON_QWEN_API_KEY.
The MCP process only reads the platform knowledge base through Chilon services.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from app import settings  # noqa: E402
from app.services import teaching_agent  # noqa: E402

server = MCPServer(
    name='chilon',
    title='Chilon Teaching Knowledge',
    instructions=(
        'Chilon high school mathematics knowledge base. Use these tools to retrieve '
        'real textbook content, Gaokao/mock questions and source metadata. Never '
        'invent a source, year or question that a tool did not return.'
    ),
    version='1.0',
)


def _db_dsn() -> str:
    dsn = settings.get('CHILON_DATABASE_URL') or settings.get('CHILON_TEST_DATABASE_URL')
    if not dsn:
        raise RuntimeError('CHILON_DATABASE_URL is not configured')
    return dsn.replace('postgresql+psycopg://', 'postgresql://')


def _connect():
    import psycopg

    return psycopg.connect(_db_dsn(), connect_timeout=5)


@server.tool()
def search_knowledge(query: str, source_types: list[str] | None = None,
                     year_range: dict | None = None,
                     question_types: list[str] | None = None,
                     knowledge_points: list[str] | None = None,
                     limit: int = 10) -> dict:
    """Search real textbooks, Gaokao papers and mock exams in Chilon.

    source_types accepts textbook / gaokao / mock_exam. The response reports the
    actual returned count and preserves source/year/locator metadata.
    """
    return teaching_agent.search_knowledge(
        query, limit=limit, source_types=source_types, year_range=year_range,
        question_types=question_types, knowledge_points=knowledge_points,
    )


@server.tool()
def get_textbook_content(query: str, grade: str | None = None,
                         volume: str | None = None, limit: int = 8) -> dict:
    """Retrieve textbook chunks (definitions, formulas, examples) by query."""
    return teaching_agent.textbook_content(
        query, grade=grade, volume=volume, limit=limit,
    )


@server.tool()
def get_question_detail(question_id: str) -> dict:
    """Get the full stem, answer and verified source of one question by UUID."""
    try:
        qid = __import__('uuid').UUID(question_id)
    except (ValueError, TypeError):
        return teaching_agent.envelope(False, code='VALIDATION_ERROR',
                                       message='question_id must be a UUID')
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT q.id::text, q.question_no, q.current_paper_question_type,
                   q.current_knowledge_points, qc.text_content, ac.text_content,
                   s.id::text, s.title, s.source_type, s.year, s.exam_paper,
                   s.paper_name, q.stem_locator::text
            FROM knowledge_questions q
            JOIN knowledge_document_versions v ON v.id = q.document_version_id
            JOIN knowledge_sources s ON s.id = v.source_id
            LEFT JOIN knowledge_chunks qc
                   ON qc.document_version_id = q.document_version_id
                  AND qc.locator = q.stem_locator
            LEFT JOIN knowledge_chunks ac
                   ON ac.document_version_id = q.document_version_id
                  AND ac.locator = q.answer_locator
            WHERE q.id = %s AND q.deleted_at IS NULL
        """, (str(qid),))
        row = cur.fetchone()
    if row is None:
        return teaching_agent.envelope(False, code='RESOURCE_NOT_FOUND',
                                       message='question not found')
    return teaching_agent.envelope(True, {
        'question_id': row[0], 'question_no': row[1], 'question_type': row[2],
        'knowledge_points': row[3] or [], 'content': row[4], 'answer': row[5],
        'explanation': row[5],
        'source': {
            'source_id': row[6], 'name': row[7], 'source_type': row[8],
            'year': row[9], 'exam_paper': row[10] or row[11], 'locator': row[12],
        },
    })


@server.tool()
def get_source_detail(source_id: str) -> dict:
    """Get metadata for a textbook/paper/mock source by UUID."""
    try:
        sid = __import__('uuid').UUID(source_id)
    except (ValueError, TypeError):
        return teaching_agent.envelope(False, code='VALIDATION_ERROR',
                                       message='source_id must be a UUID')
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT s.id::text, s.title, s.source_type, s.year, s.exam_paper,
                   s.paper_name, s.publisher, s.region, s.rights_status,
                   count(DISTINCT v.id), count(DISTINCT c.id)
            FROM knowledge_sources s
            LEFT JOIN knowledge_document_versions v ON v.source_id = s.id
            LEFT JOIN knowledge_chunks c ON c.document_version_id = v.id
            WHERE s.id = %s AND s.deleted_at IS NULL
            GROUP BY s.id
        """, (str(sid),))
        row = cur.fetchone()
    if row is None:
        return teaching_agent.envelope(False, code='RESOURCE_NOT_FOUND',
                                       message='source not found')
    return teaching_agent.envelope(True, {
        'source_id': row[0], 'name': row[1], 'source_type': row[2],
        'year': row[3], 'exam_paper': row[4] or row[5],
        'publisher': row[6], 'region': row[7], 'rights_status': row[8],
        'versions': row[9], 'chunks': row[10],
    })


@server.tool()
def calculate_math(expression: str) -> dict:
    """Safely evaluate basic arithmetic; supports sqrt/sin/cos/log/exp etc."""
    return teaching_agent.calculate_math(expression)


if __name__ == '__main__':
    # psycopg async is not used here; stdio transport is synchronous tools.
    server.run('stdio')
