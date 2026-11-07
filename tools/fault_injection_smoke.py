"""Fault-injection smoke for retrieval degradation paths.

Tests:
  1. /retrieval/search returns 503 when the routed service fails;
  2. agent knowledge_search falls back to legacy when routed retrieval fails;
  3. /retrieval/health reports degraded (HTTP 200) when Qdrant is unreachable.

No real Qwen/Qdrant call is required for 1 and 2.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))


def main() -> int:
    os.environ['CHILON_AGENT_SEARCH_MODE'] = 'hybrid_h'
    os.environ['CHILON_RETRIEVAL_ROUTER'] = 'off'
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import current_user
    from app.services import routed_retrieval
    from app.tools import impl

    app.dependency_overrides[current_user] = lambda: uuid.UUID('00000000-0000-0000-0000-000000000099')
    client = TestClient(app)

    original_search = routed_retrieval.search

    def broken_search(*args, **kwargs):
        raise RuntimeError('injected retrieval outage')

    routed_retrieval.search = broken_search
    try:
        response = client.post('/retrieval/search', json={'query': '三角函数', 'limit': 2, 'mode': 'h'})
        print('api_failure', response.status_code)
        if response.status_code != 503:
            print(f'FAIL: expected 503, got {response.status_code}')
            return 1
    finally:
        routed_retrieval.search = original_search

    original_legacy = impl._legacy_knowledge_search

    async def fake_legacy(session, ctx):
        return {'topic': ctx.requirement.get('topic'), 'hit_count': 1,
                'hits': [{'chunk_id': 'fake', 'question_id': None, 'question_no': None,
                          'question_type': None, 'knowledge_points': [], 'answer': None,
                          'source_id': 'fake', 'source_title': 'fake', 'source_type': 'textbook',
                          'year': None, 'source_paper': None, 'document_version_id': 'fake',
                          'locator': '{}', 'excerpt': 'fake'}]}

    impl._legacy_knowledge_search = fake_legacy
    routed_retrieval.search = broken_search
    try:
        ctx = impl.ToolContext(
            owner_id=uuid.uuid4(), execution_id=uuid.uuid4(), step_key='fault',
            spec={'limit': 2}, requirement={'topic': '三角函数', 'sources': []}, deps={},
        )
        result = asyncio.run(impl.knowledge_search(None, ctx))
        print('tool_fallback', result.get('retrieval', {}).get('mode'))
        if result.get('retrieval', {}).get('mode') != 'legacy_fallback':
            print('FAIL: tool did not fall back to legacy')
            return 1
    finally:
        impl._legacy_knowledge_search = original_legacy
        routed_retrieval.search = original_search

    old_qdrant = os.environ.get('QDRANT_URL')
    os.environ['QDRANT_URL'] = 'http://127.0.0.1:1'
    try:
        health = client.get('/retrieval/health')
        print('health', health.status_code, health.json().get('status'))
        if health.status_code != 200 or health.json().get('status') != 'degraded':
            print('FAIL: health did not report degraded')
            return 1
    finally:
        if old_qdrant is None:
            os.environ.pop('QDRANT_URL', None)
        else:
            os.environ['QDRANT_URL'] = old_qdrant

    print('PASS: fault injection (503, legacy fallback, degraded health)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
