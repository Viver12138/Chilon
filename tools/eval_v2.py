"""Evaluate v2.0 (chunk_id strict gold) on five retrieval groups.

Groups:
    L   legacy knowledge_search (old engine; historical comparison)
    T   pg_trgm text only
    V   Qdrant vector only (Qwen API index)
    H   hybrid text+vector RRF + rare-term rescue (current default)
    HR  H + qwen3.7-text-rerank API

Usage:
    .\\.venv\\Scripts\\python.exe tools\\eval_v2.py `
        --database-url "postgresql+psycopg://postgres:<pw>@127.0.0.1:55495/chilon" `
        --out-prefix var/retrieval/v2_eval_2026-11-07
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))

from app.services import hybrid_retrieval as hr  # noqa: E402
import eval_retrieval as legacy_eval  # noqa: E402
import qwen_api  # noqa: E402

DEFAULT_DATASET = ROOT / 'corpus/eval/teacher_questions.v2.json'
DEFAULT_COLLECTION = 'chilon_chunks_qwen3_7_text_embedding_v1'
DEFAULT_OUT = ROOT / 'var/retrieval/v2_eval_2026-11-07'
K = 8


def normalize_clause(clause):
    if isinstance(clause, str):
        return {'field': 'text', 'contains': clause}
    return clause


def judge(hits: list[dict], query: dict, k: int = K) -> dict:
    top = hits[:k]
    any_clauses = [normalize_clause(c) for c in query['expect']['any']]
    strict = query['expect'].get('strict')
    gold = set(strict['chunk_ids']) if strict else set()
    row = {
        'id': query['id'], 'category': query['category'], 'text': query['text'],
        'lenient_rank': None, 'strict_rank': None,
        'strict_all_hit': False, 'hits': len(top), 'top_ids': [h.get('chunk_id') for h in top],
    }
    for position, hit in enumerate(top, 1):
        if row['lenient_rank'] is None and any(
            legacy_eval.clause_matches(hit, clause) for clause in any_clauses
        ):
            row['lenient_rank'] = position
        if gold and row['strict_rank'] is None and hit.get('chunk_id') in gold:
            row['strict_rank'] = position
    row['strict_all_hit'] = bool(gold) and gold.issubset({h.get('chunk_id') for h in top})
    row['status'] = 'empty' if not top else ('hit' if row['lenient_rank'] else 'miss')
    row['strict_status'] = None if not gold else ('hit' if row['strict_rank'] else 'miss')
    return row


def metrics(rows: list[dict], k: int = K) -> dict:
    total = len(rows)
    found = [r['lenient_rank'] for r in rows if r['lenient_rank']]
    empty = sum(1 for r in rows if not r['hits'])
    strict_rows = [r for r in rows if r['strict_status'] is not None]
    strict_found = [r['strict_rank'] for r in strict_rows if r['strict_rank']]
    return {
        'queries': total,
        'recall_at_8': len(found) / total if total else None,
        'found': len(found),
        'mrr_at_8': sum(1.0 / rank for rank in found) / total if total else None,
        'empty': empty,
        'empty_rate': empty / total if total else None,
        'hits_but_miss': sum(1 for r in rows if r['hits'] and not r['lenient_rank']),
        'strict_queries': len(strict_rows),
        'strict_found': len(strict_found),
        'strict_recall_at_8': len(strict_found) / len(strict_rows) if strict_rows else None,
        'strict_mrr_at_8': (
            sum(1.0 / rank for rank in strict_found) / len(strict_rows) if strict_rows else None
        ),
        'strict_at_1': (
            sum(1 for r in strict_rows if r['strict_rank'] == 1) / len(strict_rows)
            if strict_rows else None
        ),
        'strict_all_at_8': (
            sum(1 for r in strict_rows if r['strict_all_hit']) / len(strict_rows)
            if strict_rows else None
        ),
        'strict_rank_distribution': dict(Counter(
            str(r['strict_rank']) if r['strict_rank'] else 'miss' for r in strict_rows
        )),
    }


def group_summary(rows: list[dict], k: int = K) -> dict:
    by_category = {}
    for category in ('主题词', '题型+知识点', '教材概念', '年份+卷别', '自然语言要求'):
        subset = [r for r in rows if r['category'] == category]
        if subset:
            by_category[category] = metrics(subset, k)
    return {'metrics': metrics(rows, k), 'by_category': by_category, 'queries': rows}


def bootstrap_ci(rows: list[dict], n: int = 1000, seed: int = 42) -> dict:
    """Query-level bootstrap 95% CI for the headline metrics."""
    if not rows:
        return {}
    rng = random.Random(seed)
    keys = ('recall_at_8', 'mrr_at_8', 'strict_recall_at_8', 'strict_mrr_at_8',
            'strict_at_1', 'strict_all_at_8')
    samples = {key: [] for key in keys}
    for _ in range(n):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        m = metrics(sample)
        for key in keys:
            if m.get(key) is not None:
                samples[key].append(float(m[key]))
    result = {}
    for key, values in samples.items():
        if not values:
            continue
        values.sort()
        lo = values[int(0.025 * (len(values) - 1))]
        hi = values[int(0.975 * (len(values) - 1))]
        result[key] = {'point': round(metrics(rows).get(key), 4), 'lo': round(lo, 4), 'hi': round(hi, 4)}
    return result


def hydrate_vector_hits(conn, vector_hits: list[dict]) -> list[dict]:
    ids = [h['chunk_id'] for h in vector_hits if h.get('chunk_id')]
    hydrated = hr.fetch_chunks(conn, ids)
    out = []
    for hit in vector_hits:
        full = hydrated.get(hit['chunk_id'])
        if not full:
            continue
        merged = dict(full)
        merged['vector_score'] = hit.get('vector_score')
        out.append(merged)
    return out


def hybrid_hits(conn, client, query_text: str, vector: list[float], collection: str):
    conditions = hr.extract_conditions(query_text)
    text_hits, rare_hits, _missing, rare_rescue = hr.text_search_with_rare_rescue(
        conn, query_text, conditions
    )
    if not rare_rescue and len(text_hits) < hr.CONFIG['min_filtered_hits']:
        text_hits = hr.text_search(conn, query_text, conditions, use_filters=False)
    vector_hits = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=True)
    if len(vector_hits) < hr.CONFIG['min_filtered_hits']:
        vector_hits = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=False)
    vector_full = hydrate_vector_hits(conn, vector_hits)
    if rare_rescue:
        return hr.rrf_fuse([text_hits, vector_full, rare_hits], weights=[1.0, 1.0, 3.0])
    return hr.rrf_fuse([text_hits, vector_full])


def run_legacy(queries: list[dict], dsn: str, limit: int = 8) -> dict[str, list[dict]]:
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    from app.db import session as db
    from app.tools import impl as tools_impl

    def ctx(topic: str):
        return tools_impl.ToolContext(
            owner_id=uuid.uuid4(), execution_id=uuid.uuid4(), step_key='v2-eval',
            spec={'limit': limit}, requirement={'topic': topic, 'sources': []}, deps={},
        )

    async def _inner() -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        await db.init(dsn) if asyncio.iscoroutinefunction(db.init) else db.init(dsn)
        try:
            for query in queries:
                async with db.system_session() as session:
                    result = await tools_impl.knowledge_search(session, ctx(query['text']))
                out[query['id']] = (result.get('hits') or [])[:limit]
        finally:
            await db.dispose()
        return out

    return asyncio.run(_inner())


def render_md(doc: dict) -> str:
    lines = [
        '# v2.0 检索评测（60 条 / 20 strict）', '',
        f"- 数据集：`{doc['dataset']['path']}`（sha256 `{doc['dataset']['sha256'][:16]}…`）",
        f"- 索引：`{doc['index']['collection']}` / {doc['index']['points']} points",
        f"- 生成：{doc['generated_at']}，git `{doc['git_commit']}`",
        '', '## 总览', '',
        '| 组 | Recall@8 | MRR@8 | Strict Recall@8 | Strict MRR@8 | Strict@1 | Strict-all@8 | 空结果 | 耗时 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for key, group in doc['groups'].items():
        m = group['metrics']
        def pct(x):
            return '—' if x is None else f'{x:.1%}'
        def num(x):
            return '—' if x is None else f'{x:.3f}'
        lines.append(
            f"| {group['label']} | {pct(m['recall_at_8'])} | {num(m['mrr_at_8'])} | "
            f"{pct(m['strict_recall_at_8'])} | {num(m['strict_mrr_at_8'])} | "
            f"{pct(m['strict_at_1'])} | {pct(m['strict_all_at_8'])} | "
            f"{m['empty']}/{m['queries']} | {group['seconds']:.1f}s |"
        )
    lines += ['', '### 95% bootstrap CI（query-level 重采样）', '']
    lines += ['| 组 | Recall@8 点估计 [95% CI] | Strict Recall@8 点估计 [95% CI] |']
    lines += ['| --- | --- | --- |']
    for key, group in doc['groups'].items():
        ci = group.get('ci_95') or {}
        def fmt(metric):
            item = ci.get(metric)
            if not item:
                return '—'
            return f"{item['point']:.3f} [{item['lo']:.3f}, {item['hi']:.3f}]"
        lines.append(f"| {group['label']} | {fmt('recall_at_8')} | {fmt('strict_recall_at_8')} |")
    lines += ['', '## 分类别（strict Recall@8）', '']
    for key, group in doc['groups'].items():
        lines.append(f"### {group['label']}")
        lines.append('| 类别 | 条数 | Recall@8 | strict Recall@8 |')
        lines.append('| --- | ---: | ---: | ---: |')
        for category, cat in group['by_category'].items():
            def pct2(x):
                return '—' if x is None else f'{x:.1%}'
            lines.append(f"| {category} | {cat['queries']} | {pct2(cat['recall_at_8'])} | {pct2(cat['strict_recall_at_8'])} |")
        lines.append('')
    lines += ['## 边界', '',
              '- 20 条 strict（定义9/定理6/公式5），非模板计划的 30；B01 焦点弦无独立教材公式块降 any-only。',
              '- L 组走旧 `knowledge_search`，不代表新索引；T/V 为消融路径，H 为当前默认，HR 用 API rerank。',
              '- lenient 判定为 v1 片段口径；strict 判定为 chunk_id 集合。']
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Evaluate teacher_questions.v2 on five retrieval groups')
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--database-url', default=os.environ.get('CHILON_TEST_DATABASE_URL'))
    parser.add_argument('--qdrant-url', default=os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333'))
    parser.add_argument('--collection', default=DEFAULT_COLLECTION)
    parser.add_argument('--out-prefix', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--limit-queries', type=int, default=0)
    parser.add_argument('--skip-legacy', action='store_true')
    parser.add_argument('--bootstrap', type=int, default=1000, help='bootstrap resamples (0 = off)')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if not args.database_url:
        print('CHILON_TEST_DATABASE_URL is not set (or pass --database-url)', file=sys.stderr)
        return 2

    started = time.perf_counter()
    dataset_bytes = args.dataset.read_bytes()
    data = json.loads(dataset_bytes)
    queries = data['queries']
    if args.limit_queries:
        queries = queries[: args.limit_queries]
    print(f'queries: {len(queries)} (strict {sum(1 for q in queries if q["expect"].get("strict"))})')

    import psycopg
    from qdrant_client import QdrantClient

    dsn_pg = args.database_url.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn_pg, connect_timeout=10)
    client = QdrantClient(url=args.qdrant_url, timeout=120)
    points = client.count(collection_name=args.collection, exact=True).count
    print(f'collection {args.collection}: {points} points')

    print('embedding queries via Qwen API ...')
    vectors, embed_stats = qwen_api.embed_texts([q['text'] for q in queries])
    print(f'   {embed_stats}')
    vector_by_id = {q['id']: v for q, v in zip(queries, vectors)}

    legacy_hits = {}
    legacy_seconds = 0.0
    if not args.skip_legacy:
        print('running legacy knowledge_search ...')
        t0 = time.perf_counter()
        legacy_hits = run_legacy(queries, args.database_url)
        legacy_seconds = time.perf_counter() - t0
        print(f'   legacy done in {legacy_seconds:.1f}s')

    groups: dict[str, dict] = {}
    timings: dict[str, list[float]] = {}

    def add_group(key: str, label: str, seconds: float, rows: list[dict]):
        groups[key] = {
            'label': label,
            'seconds': round(seconds, 2),
            **group_summary(rows),
            'ci_95': bootstrap_ci(rows, args.bootstrap, args.seed) if args.bootstrap else {},
        }

    if legacy_hits:
        rows = [judge(legacy_hits[q['id']], q) for q in queries]
        add_group('L', 'L 旧 knowledge_search（历史对照）', legacy_seconds, rows)

    # T: pg_trgm text only
    t0 = time.perf_counter()
    rows = []
    for q in queries:
        conditions = hr.extract_conditions(q['text'])
        hits = hr.text_search(conn, q['text'], conditions, use_filters=True)
        if len(hits) < hr.CONFIG['min_filtered_hits']:
            hits = hr.text_search(conn, q['text'], conditions, use_filters=False)
        rows.append(judge(hits, q))
    add_group('T', 'T 仅 pg_trgm 文本', time.perf_counter() - t0, rows)

    # V: vector only
    t0 = time.perf_counter()
    rows = []
    for q in queries:
        conditions = hr.extract_conditions(q['text'])
        hits = hr.vector_search(client, args.collection, vector_by_id[q['id']], conditions=conditions, use_filters=True)
        if len(hits) < hr.CONFIG['min_filtered_hits']:
            hits = hr.vector_search(client, args.collection, vector_by_id[q['id']], conditions=conditions, use_filters=False)
        rows.append(judge(hydrate_vector_hits(conn, hits), q))
    add_group('V', 'V 仅 Qdrant 向量', time.perf_counter() - t0, rows)

    # H
    t0 = time.perf_counter()
    rows_h = []
    fused_by_id = {}
    for q in queries:
        fused = hybrid_hits(conn, client, q['text'], vector_by_id[q['id']], args.collection)
        fused_by_id[q['id']] = fused
        rows_h.append(judge(fused, q))
    add_group('H', 'H 混合（文本 + 向量 + RRF + 稀有词 rescue）', time.perf_counter() - t0, rows_h)

    # HR
    t0 = time.perf_counter()
    rows_hr = []
    rerank_stats = []
    for q in queries:
        candidates = fused_by_id[q['id']][: hr.CONFIG['rerank_candidates']]
        docs = [hr.embedding_text(hit)[: hr.CONFIG['rerank_doc_chars']] for hit in candidates]
        scores, stats = qwen_api.rerank(q['text'], docs)
        rerank_stats.append(stats)
        ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        enriched = []
        for hit, score in ranked:
            item = dict(hit)
            item['rerank_score'] = score
            enriched.append(item)
        rows_hr.append(judge(enriched, q))
    add_group('HR', 'HR 混合 + qwen3.7-text-rerank（API）', time.perf_counter() - t0, rows_hr)

    doc = {
        'dataset': {
            'path': args.dataset.relative_to(ROOT).as_posix(),
            'sha256': hashlib.sha256(dataset_bytes).hexdigest(),
            'queries': len(queries),
            'strict_queries': sum(1 for q in queries if q['expect'].get('strict')),
        },
        'index': {'collection': args.collection, 'points': points, 'qdrant_url': args.qdrant_url},
        'models': {
            'embedding': {'provider': 'dashscope', 'model': qwen_api.embedding_model(), 'dim': qwen_api.embedding_dimension()},
            'reranker': {'provider': 'dashscope', 'model': qwen_api.rerank_model()},
        },
        'query_embedding': embed_stats,
        'bootstrap': {'resamples': args.bootstrap, 'seed': args.seed},
        'rerank': {
            'calls': len(rerank_stats),
            'documents': sum(s['pairs'] for s in rerank_stats),
            'seconds': round(sum(s['seconds'] for s in rerank_stats), 2),
        },
        'groups': groups,
        'generated_at': hr.now_iso(),
        'git_commit': hr._git_commit(),
        'elapsed_seconds': round(time.perf_counter() - started, 1),
    }
    json_path = Path(str(args.out_prefix) + '.json')
    md_path = Path(str(args.out_prefix) + '.md')
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md_path.write_text(render_md(doc), encoding='utf-8')
    conn.close()

    for key in ('L', 'T', 'V', 'H', 'HR'):
        if key not in groups:
            continue
        m = groups[key]['metrics']
        print(f"{key}: Recall@8={m['found']}/{m['queries']} MRR={m['mrr_at_8']:.3f} "
              f"strict={m['strict_found']}/{m['strict_queries']} ({m['strict_recall_at_8']:.1%}) "
              f"strictMRR={m['strict_mrr_at_8']:.3f} strict@1={m['strict_at_1']:.1%} "
              f"strict-all@8={m['strict_all_at_8']:.1%}")
        ci = groups[key].get('ci_95') or {}
        if ci.get('recall_at_8'):
            r = ci['recall_at_8']
            s = ci.get('strict_recall_at_8')
            print(f"   95% CI Recall [{r['lo']:.3f}, {r['hi']:.3f}]"
                  + (f"; strict [{s['lo']:.3f}, {s['hi']:.3f}]" if s else ""))
    print(f'JSON: {json_path}')
    print(f'MD  : {md_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
