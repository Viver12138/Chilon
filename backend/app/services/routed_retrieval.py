"""Phase-2 routed retrieval: actual H/HR hits behind the gray router.

Used by `POST /retrieval/search`. It is intentionally synchronous (psycopg +
qdrant-client + Qwen HTTP) and the API calls it in a threadpool.

Environment:
  CHILON_DATABASE_URL / CHILON_TEST_DATABASE_URL
  QDRANT_URL (default http://127.0.0.1:6333)
  CHILON_QDRANT_COLLECTION (default chilon_chunks_qwen3_7_text_embedding_v1)
  CHILON_RETRIEVAL_ROUTER=off|shadow|on + PERCENT
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

from app import settings
from app.services import hybrid_retrieval as hr
from app.services import query_plan, retrieval_router, shadow_log

DEFAULT_COLLECTION = 'chilon_chunks_qwen3_7_text_embedding_v1'


def _db_dsn() -> str:
    dsn = settings.get('CHILON_DATABASE_URL') or settings.get('CHILON_TEST_DATABASE_URL')
    if not dsn:
        raise RuntimeError('CHILON_DATABASE_URL is not configured')
    return dsn.replace('postgresql+psycopg://', 'postgresql://')


def _qwen_key() -> str:
    key = settings.get('CHILON_QWEN_API_KEY') or settings.get('DASHSCOPE_API_KEY')
    if not key:
        raise RuntimeError('CHILON_QWEN_API_KEY is not configured')
    return key


def _qwen_base() -> str:
    return (settings.get('CHILON_QWEN_BASE_URL') or 'https://dashscope.aliyuncs.com/api/v1').rstrip('/')


def embed_query(query: str) -> list[float]:
    model = settings.get('CHILON_QWEN_EMBEDDING_MODEL', 'qwen3.7-text-embedding')
    dim = int(settings.get('CHILON_QWEN_EMBEDDING_DIM', '1024'))
    payload = {'model': model, 'input': {'texts': [query]}, 'parameters': {'dimension': dim}}
    headers = {'Authorization': f'Bearer {_qwen_key()}', 'Content-Type': 'application/json'}
    with httpx.Client(timeout=60) as client:
        response = client.post(f'{_qwen_base()}/services/embeddings/text-embedding/text-embedding',
                               headers=headers, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f'embedding HTTP {response.status_code}: {response.text[:300]}')
    body = response.json()
    embeddings = sorted(body['output']['embeddings'], key=lambda x: int(x.get('text_index', 0)))
    return list(embeddings[0]['embedding'])


def rerank(query: str, documents: list[str], top_n: int = 40) -> list[float]:
    if not documents:
        return []
    model = settings.get('CHILON_QWEN_RERANK_MODEL', 'qwen3.7-text-rerank')
    payload = {
        'model': model,
        'input': {'query': query, 'documents': documents},
        'parameters': {'top_n': min(top_n, len(documents)), 'return_documents': False},
    }
    headers = {'Authorization': f'Bearer {_qwen_key()}', 'Content-Type': 'application/json'}
    with httpx.Client(timeout=120) as client:
        response = client.post(f'{_qwen_base()}/services/rerank/text-rerank/text-rerank',
                               headers=headers, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f'rerank HTTP {response.status_code}: {response.text[:300]}')
    scores = [0.0] * len(documents)
    for item in response.json()['output']['results']:
        idx = int(item.get('index', -1))
        if 0 <= idx < len(scores):
            scores[idx] = float(item.get('relevance_score') or 0.0)
    return scores


def _hydrate(conn, vector_hits: list[dict]) -> list[dict]:
    ids = [str(hit.get('chunk_id')) for hit in vector_hits if hit.get('chunk_id')]
    if not ids:
        return []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.id::text, c.text_content, s.title, s.source_type, s.year,
                   s.exam_paper, q.current_paper_question_type, c.locator::text,
                   q.id::text AS question_id, q.question_no,
                   q.current_knowledge_points, ac.text_content AS answer_text,
                   s.id::text AS source_id, dv.id::text AS document_version_id
            FROM knowledge_chunks c
            JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
            JOIN knowledge_sources s ON s.id = dv.source_id
            LEFT JOIN knowledge_questions q
              ON q.document_version_id = dv.id AND q.stem_locator = c.locator
            LEFT JOIN knowledge_chunks ac
              ON ac.document_version_id = dv.id AND ac.locator = q.answer_locator
            WHERE c.id = ANY(%s::uuid[])
        """, (ids,))
        rows = {r[0]: r for r in cur.fetchall()}
    out = []
    for hit in vector_hits:
        cid = str(hit.get('chunk_id'))
        row = rows.get(cid)
        if not row:
            continue
        out.append({
            'chunk_id': cid,
            'excerpt': (row[1] or '')[:400],
            'source_title': row[2],
            'source_type': row[3],
            'year': row[4],
            'source_paper': row[5],
            'question_type': row[6],
            'locator': row[7],
            'question_id': row[8],
            'question_no': row[9],
            'knowledge_points': list(row[10] or []),
            'answer': row[11],
            'source_id': row[12],
            'document_version_id': row[13],
            'vector_score': hit.get('vector_score'),
        })
    return out


def _search_impl(query: str, *, limit: int = 8, mode: str = 'auto', user_key: str = '',
                 sources: list[str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    plan = query_plan.build_plan(query)
    if mode in ('h', 'hr'):
        selected = mode.upper()
        auto_mode = query_plan.preferred_mode(plan)
        router_flag = 'manual'
        shadow = None
    else:
        decision = retrieval_router.decide(query, user_key=user_key)
        selected = decision['mode']
        auto_mode = decision['auto_mode']
        router_flag = decision['router_flag']
        shadow = decision['shadow_mode']

    conditions = dict(plan['hard'])
    conditions['keywords'] = list(plan['soft'].get('keywords') or [])
    if sources:
        conditions['source_types'] = list(sources)
    hard = bool(plan['hard']) or bool(sources)

    import psycopg
    from qdrant_client import QdrantClient

    conn = psycopg.connect(_db_dsn(), connect_timeout=10)
    client = QdrantClient(url=os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333'), timeout=120)
    collection = os.environ.get('CHILON_QDRANT_COLLECTION', DEFAULT_COLLECTION)
    try:
        vector = embed_query(query)
        if hard:
            text_hits = hr.text_search(conn, query, conditions, use_filters=True)
            rare_hits, rescue = [], False
        else:
            text_hits, rare_hits, _missing, rescue = hr.text_search_with_rare_rescue(conn, query, conditions)
        if not hard and not rescue and len(text_hits) < hr.CONFIG['min_filtered_hits']:
            text_hits = hr.text_search(conn, query, conditions, use_filters=False)
        vec_raw = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=True)
        if not hard and len(vec_raw) < hr.CONFIG['min_filtered_hits']:
            vec_raw = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=False)
        vec_hits = _hydrate(conn, vec_raw)
        if rescue:
            hits = hr.rrf_fuse([text_hits, vec_hits, rare_hits], weights=[1.0, 1.0, 3.0])
        else:
            hits = hr.rrf_fuse([text_hits, vec_hits])
        if selected == 'HR':
            candidates = hits[: hr.CONFIG['rerank_candidates']]
            docs = [hr.embedding_text(h)[: hr.CONFIG['rerank_doc_chars']] for h in candidates]
            scores = rerank(query, docs, hr.CONFIG['rerank_candidates'])
            ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
            hits = []
            for h, score in ranked:
                item = dict(h)
                item['rerank_score'] = score
                hits.append(item)
        final_hits = hits[:limit]
        enriched = {h['chunk_id']: h for h in _hydrate(conn, final_hits)}
        final = []
        for rank, hit in enumerate(final_hits, 1):
            cid = hit.get('chunk_id')
            base = dict(enriched.get(cid) or {})
            base.update({k: v for k, v in hit.items() if v is not None})
            final.append({
                'rank': rank,
                'chunk_id': cid,
                'question_id': base.get('question_id'),
                'question_no': base.get('question_no'),
                'question_type': base.get('question_type'),
                'knowledge_points': base.get('knowledge_points') or [],
                'answer': base.get('answer'),
                'source_id': base.get('source_id'),
                'source_title': base.get('source_title'),
                'source_type': base.get('source_type'),
                'year': base.get('year'),
                'source_paper': base.get('source_paper'),
                'document_version_id': base.get('document_version_id'),
                'locator': base.get('locator'),
                'excerpt': (base.get('excerpt') or '')[:400],
                'rrf_score': base.get('rrf_score'),
                'rerank_score': base.get('rerank_score'),
            })
        candidate_count = len(hits)
        if final:
            status = 'ok'
            empty_reason = None
        else:
            status = 'empty'
            empty_reason = 'no_candidates' if candidate_count == 0 else (
                'no_match_under_filters' if hard else 'no_match'
            )
        if router_flag in ('shadow', 'on'):
            shadow_log.append({
                'source': 'retrieval-service',
                'query': query[:500],
                'user_hash': shadow_log.user_hash(user_key),
                'mode': selected,
                'auto_mode': auto_mode,
                'shadow_mode': shadow,
                'router_flag': router_flag,
                'plan_intent': plan.get('intent'),
                'hard_filters': plan.get('hard'),
                'hit_count': len(final),
                'empty': not final,
                'empty_reason': empty_reason,
                'candidate_count': candidate_count,
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
                'top_chunk_ids': [h.get('chunk_id') for h in final[:3]],
            })
        return {
            'query': query,
            'mode': selected,
            'auto_mode': auto_mode,
            'shadow_mode': shadow,
            'router_flag': router_flag,
            'plan': plan,
            'hits': final,
            'status': status,
            'empty_reason': empty_reason,
            'candidate_count': candidate_count,
            'hard_filters': plan['hard'],
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
        }
    finally:
        conn.close()
        client.close()


_SLOTS = threading.BoundedSemaphore(
    max(1, int(settings.get('CHILON_RETRIEVAL_MAX_CONCURRENCY', '8') or 8))
)


def search(query: str, *, limit: int = 8, mode: str = 'auto', user_key: str = '',
           sources: list[str] | None = None) -> dict[str, Any]:
    """Public entrypoint with a global concurrency cap (API + agent)."""
    try:
        timeout = float(settings.get('CHILON_RETRIEVAL_ACQUIRE_TIMEOUT_SECONDS', '5') or 5)
    except ValueError:
        timeout = 5.0
    if not _SLOTS.acquire(timeout=timeout):
        raise RuntimeError('retrieval busy: concurrency cap reached')
    try:
        return _search_impl(query, limit=limit, mode=mode, user_key=user_key, sources=sources)
    finally:
        _SLOTS.release()
