"""Read-only health probe for the retrieval dependencies.

No Qwen completion is called (that would cost money); the probe only checks
configuration presence, Postgres connectivity and the Qdrant collection.
"""

from __future__ import annotations

import os
import time

from app import settings

DEFAULT_COLLECTION = 'chilon_chunks_qwen3_7_text_embedding_v1'


def check() -> dict:
    started = time.perf_counter()
    components = {}
    healthy = True

    db_url = settings.get('CHILON_DATABASE_URL') or settings.get('CHILON_TEST_DATABASE_URL')
    if not db_url:
        components['postgres'] = {'ok': False, 'error': 'CHILON_DATABASE_URL missing'}
        healthy = False
    else:
        try:
            import psycopg
            with psycopg.connect(db_url.replace('postgresql+psycopg://', 'postgresql://'),
                                 connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1')
                    cur.fetchone()
            components['postgres'] = {'ok': True}
        except Exception as exc:  # noqa: BLE001
            components['postgres'] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:200]}
            healthy = False

    qdrant_url = os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333')
    collection = os.environ.get('CHILON_QDRANT_COLLECTION', DEFAULT_COLLECTION)
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=qdrant_url, timeout=5)
        info = client.get_collection(collection)
        client.close()
        components['qdrant'] = {'ok': True, 'collection': collection, 'points': getattr(info, 'points_count', None)}
    except Exception as exc:  # noqa: BLE001
        components['qdrant'] = {'ok': False, 'collection': collection,
                                'error': f'{type(exc).__name__}: {exc}'[:200]}
        healthy = False

    qwen_key = settings.get('CHILON_QWEN_API_KEY') or settings.get('DASHSCOPE_API_KEY')
    components['qwen'] = {'ok': bool(qwen_key), 'configured': bool(qwen_key)}
    if not qwen_key:
        healthy = False

    return {
        'status': 'ok' if healthy else 'degraded',
        'healthy': healthy,
        'components': components,
        'router_flag': settings.get('CHILON_RETRIEVAL_ROUTER', 'off'),
        'agent_search_mode': settings.get('CHILON_AGENT_SEARCH_MODE', 'legacy'),
        'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
    }
