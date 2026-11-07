"""Hybrid-H E2E smoke with a Qdrant test fixture.

Unlike test_executor (which only has Postgres), this seeds the same test chunk
into a disposable Qdrant collection, then calls the real agent tools with
CHILON_AGENT_SEARCH_MODE=hybrid_h.

Requires:
  CHILON_TEST_DATABASE_URL (postgres:chilon_test_only@...)
  QDRANT_URL
  Qwen key in .env

    $env:CHILON_TEST_DATABASE_URL='postgresql+psycopg://postgres:chilon_test_only@127.0.0.1:55495/chilon'
    .\\.venv\\Scripts\\python.exe tools\\smoke_hybrid_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

COLLECTION = 'chilon_e2e_hybrid'
QUERY = '用高考题出 4 道三角函数题'


async def main() -> int:
    url = os.environ.get('CHILON_TEST_DATABASE_URL')
    if not url:
        print('CHILON_TEST_DATABASE_URL is not set')
        return 2
    os.environ['CHILON_AGENT_SEARCH_MODE'] = 'hybrid_h'
    os.environ['CHILON_RETRIEVAL_ROUTER'] = 'off'
    os.environ['CHILON_QDRANT_COLLECTION'] = COLLECTION

    from sqlalchemy import text
    from qdrant_client import QdrantClient, models as qm

    from app.db import session as db
    from app.services import routed_retrieval
    from app.tools import impl
    from tests.support import admin_session, provision_runtime_role
    from tests.test_executor import seed

    db.init(await provision_runtime_role(url))
    client = QdrantClient(url=os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333'), timeout=120)
    try:
        user_id, chunk_id = await seed()
        async with admin_session() as session:
            row = (
                await session.execute(
                    text("""
                        SELECT c.text_content, s.title, s.source_type, s.year, s.exam_paper
                        FROM knowledge_chunks c
                        JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
                        JOIN knowledge_sources s ON s.id = dv.source_id
                        WHERE c.id = :id
                    """),
                    {'id': chunk_id},
                )
            ).one()
        vector = routed_retrieval.embed_query(row[0])
        try:
            client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001
            pass
        client.create_collection(
            COLLECTION,
            vectors_config=qm.VectorParams(size=len(vector), distance=qm.Distance.COSINE),
        )
        client.upsert(
            COLLECTION,
            points=[qm.PointStruct(
                id=str(chunk_id),
                vector=vector,
                payload={
                    'chunk_id': str(chunk_id),
                    'source_type': row[2],
                    'year': row[3],
                    'paper': row[4],
                    'question_id': None,
                    'question_type': None,
                },
            )],
        )

        ctx = impl.ToolContext(
            owner_id=user_id,
            execution_id=uuid.uuid4(),
            step_key='hybrid-search',
            spec={'limit': 4},
            requirement={'topic': QUERY, 'sources': []},
            deps={},
        )
        search = await impl.knowledge_search(None, ctx)
        ids = [h['chunk_id'] for h in search['hits']]
        print('retrieval', search['retrieval'])
        print('hit_ids', [x[:8] for x in ids])
        if str(chunk_id) not in ids:
            print('FAIL: seeded chunk not recalled by hybrid_h')
            return 1

        gen_ctx = impl.ToolContext(
            owner_id=user_id,
            execution_id=ctx.execution_id,
            step_key='gen',
            spec={'engine': 'template', 'count': 4},
            requirement={'topic': '三角函数', 'question_count': 4},
            deps={'search': search},
        )
        generated = await impl.content_generate(None, gen_ctx)
        print('generator', generated['generator'], 'count', generated['count'])
        if generated['count'] != 4:
            print('FAIL: template generator count')
            return 1
        print('PASS: hybrid_h E2E (seed -> Qdrant -> agent search -> generate)')
        return 0
    finally:
        try:
            client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001
            pass
        client.close()
        await db.dispose()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
