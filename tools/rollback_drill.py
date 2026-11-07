"""Rollback drill: force legacy mode and prove the agent tool still works.

Sets CHILON_AGENT_SEARCH_MODE=legacy before importing, runs one real legacy
knowledge search against the configured corpus, and asserts the output uses the
legacy path. This is what operators do when rolling back from hybrid_h.

    .\\.venv\\Scripts\\python.exe tools\\rollback_drill.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['CHILON_AGENT_SEARCH_MODE'] = 'legacy'
os.environ['CHILON_RETRIEVAL_ROUTER'] = 'off'

QUERY = '三角函数的图象与性质'


async def main() -> int:
    from app import settings
    from app.db import session as db
    from app.tools import impl

    url = settings.get('CHILON_DATABASE_URL') or settings.get('CHILON_TEST_DATABASE_URL')
    if not url:
        print('CHILON_DATABASE_URL is not set')
        return 2
    db.init(url.replace('postgresql+psycopg://', 'postgresql+psycopg://'))
    try:
        ctx = impl.ToolContext(
            owner_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            step_key='rollback',
            spec={'limit': 3},
            requirement={'topic': QUERY, 'sources': []},
            deps={},
        )
        async with db.system_session() as session:
            result = await impl.knowledge_search(session, ctx)
        meta = result.get('retrieval') or {}
        print('mode', meta.get('mode'), 'search_mode', meta.get('search_mode'), 'hits', result.get('hit_count'))
        if meta.get('mode') != 'legacy':
            print('FAIL: rollback did not use legacy')
            return 1
        if not result.get('hits'):
            print('FAIL: legacy returned no hits')
            return 1
        print('PASS: rollback drill (legacy path works)')
        return 0
    finally:
        await db.dispose()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
