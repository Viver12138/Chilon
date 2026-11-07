"""P0 prototype: QueryPlan hard filters + Filter Compliance Rate.

Runs T/V/H/HR with the v0 QueryPlan hard filters (no silent fallback when a hard
filter is present), compares against the current soft-filter baseline, and reports
Filter Compliance Rate.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\eval_v2_qp.py `
        --database-url "postgresql+psycopg://postgres:...@127.0.0.1:55495/chilon" `
        --out-prefix var/retrieval/v2_eval_qp_2026-11-07
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))

from app.services import hybrid_retrieval as hr  # noqa: E402
from app.services import query_plan  # noqa: E402
import eval_v2 as base  # noqa: E402
import qwen_api  # noqa: E402

DEFAULT_DATASET = ROOT / 'corpus/eval/teacher_questions.v2.json'
DEFAULT_COLLECTION = 'chilon_chunks_qwen3_7_text_embedding_v1'
DEFAULT_OUT = ROOT / 'var/retrieval/v2_eval_qp_2026-11-07'
BASELINE = ROOT / 'var/retrieval/v2_eval_2026-11-07_rev4.json'


def hit_complies(hit: dict, hard: dict) -> bool:
    scope = hard.get('question_scope')
    if scope == 'question' and not hit.get('question_id'):
        return False
    if scope == 'knowledge' and hit.get('source_type') != 'textbook':
        return False
    if hard.get('source_types') and hit.get('source_type') not in hard['source_types']:
        return False
    if hard.get('year_range'):
        year = hit.get('year')
        if year is None or not (hard['year_range'][0] <= int(year) <= hard['year_range'][1]):
            return False
    if hard.get('papers') and hit.get('source_paper') not in hard['papers']:
        return False
    if hard.get('question_types') and hit.get('question_type') not in hard['question_types']:
        return False
    return True


def conditions_for(plan: dict) -> dict:
    conditions = dict(plan['hard'])
    conditions['keywords'] = list(plan['soft'].get('keywords') or [])
    return conditions


def text_for(conn, query: str, plan: dict):
    conditions = conditions_for(plan)
    hard = plan['hard']
    if not hard:
        hits, rare, _missing, rescue = hr.text_search_with_rare_rescue(conn, query, conditions)
        if not rescue and len(hits) < hr.CONFIG['min_filtered_hits']:
            hits = hr.text_search(conn, query, conditions, use_filters=False)
        return hits, rare, rescue
    return hr.text_search(conn, query, conditions, use_filters=True), [], False


def vector_for(client, collection: str, vector: list[float], plan: dict):
    conditions = conditions_for(plan)
    hits = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=True)
    if not plan['hard'] and len(hits) < hr.CONFIG['min_filtered_hits']:
        hits = hr.vector_search(client, collection, vector, conditions=conditions, use_filters=False)
    return hits


def summarize(rows: list[dict], k: int = base.K) -> dict:
    m = base.metrics(rows, k)
    hard_rows = [r for r in rows if r.get('hard_filters')]
    m['hard_queries'] = len(hard_rows)
    m['filter_compliance_rate'] = (
        sum(1 for r in hard_rows if r.get('all_compliant')) / len(hard_rows) if hard_rows else None
    )
    m['hit_compliance_rate'] = (
        sum(r.get('compliant_ratio', 0.0) for r in hard_rows) / len(hard_rows) if hard_rows else None
    )
    m['zero_under_hard'] = sum(1 for r in hard_rows if not r['hits'])
    return m


def group(rows: list[dict]) -> dict:
    return {'metrics': summarize(rows), 'queries': rows}


def render(doc: dict) -> str:
    lines = ['# QueryPlan P0 原型：硬过滤 + 过滤遵守率', '',
             f"- 数据集：`{doc['dataset']['path']}`（{doc['dataset']['queries']} 条 / {doc['dataset']['strict_queries']} strict）",
             f"- 索引：`{doc['collection']}`；重排：{doc['models']['reranker']}",
             f"- 计划版本：{doc['plan_version']}", '',
             '## 指标对比', '',
             '| 组 | Recall@8 | Strict Recall@8 | 过滤遵守率（查询级） | 命中遵守率（结果级） | 硬过滤查询 | 硬过滤下 0 结果 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    def pct(x):
        return '—' if x is None else f'{x:.1%}'
    for key, g in doc['groups'].items():
        m = g['metrics']
        lines.append(
            f"| {key} | {m['found']}/{m['queries']} = {pct(m['recall_at_8'])} | "
            f"{m['strict_found']}/{m['strict_queries']} = {pct(m['strict_recall_at_8'])} | "
            f"{pct(m['filter_compliance_rate'])} | {pct(m['hit_compliance_rate'])} | "
            f"{m['hard_queries']} | {m['zero_under_hard']} |"
        )
    lines += ['', '## 与当前默认（软过滤）对比', '',
              '| 组 | 基线 Recall@8 | QP Recall@8 | 基线 strict | QP strict |',
              '| --- | ---: | ---: | ---: | ---: |']
    baseline = doc.get('baseline') or {}
    for key in ('H', 'HR'):
        b = baseline.get(key) or {}
        q = doc['groups'].get(key) or {}
        if b and q:
            lines.append(
                f"| {key} | {b['recall_at_8']:.1%} | {q['metrics']['recall_at_8']:.1%} | "
                f"{b['strict_recall_at_8']:.1%} | {q['metrics']['strict_recall_at_8']:.1%} |"
            )
    lines += ['', '## 计划样例（前 10 条）', '']
    for plan in doc['plans'][:10]:
        lines.append(f"- `{plan['query']}` → intent={plan['intent']}, hard={json.dumps(plan['hard'], ensure_ascii=False)}")
    lines += ['', '## 边界', '',
              '- 本原型只做 P0：结构化硬过滤 + 遵守率；没有 content_type 分池/同义词/UI。',
              '- 硬过滤下 0 结果不静默回退；后续应在产品层展示“0 条 + 更早年份相关组”。',
              '- 评测集 60 条 / 20 strict，单次运行；不能当线上准确率。']
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='QueryPlan P0 hard-filter eval')
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--database-url', default=os.environ.get('CHILON_TEST_DATABASE_URL'))
    parser.add_argument('--qdrant-url', default=os.environ.get('QDRANT_URL', 'http://127.0.0.1:6333'))
    parser.add_argument('--collection', default=DEFAULT_COLLECTION)
    parser.add_argument('--out-prefix', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.database_url:
        print('CHILON_TEST_DATABASE_URL is not set (or pass --database-url)', file=sys.stderr)
        return 2

    started = time.perf_counter()
    dataset_bytes = args.dataset.read_bytes()
    data = json.loads(dataset_bytes)
    queries = data['queries']
    plans = [query_plan.build_plan(q['text']) for q in queries]
    print(f'queries={len(queries)} strict={sum(1 for q in queries if q["expect"].get("strict"))}')
    print(f'plans: ' + ', '.join(f"{p['intent']}={sum(1 for x in plans if x['intent']==p['intent'])}"
                                for p in {x['intent']: x for x in plans}.values()))

    import psycopg
    from qdrant_client import QdrantClient

    conn = psycopg.connect(args.database_url.replace('postgresql+psycopg://', 'postgresql://'),
                           connect_timeout=10)
    client = QdrantClient(url=args.qdrant_url, timeout=120)
    vectors, embed_stats = qwen_api.embed_texts([q['text'] for q in queries])
    vector_by_id = {q['id']: v for q, v in zip(queries, vectors)}

    def rows_for(group_key: str) -> list[dict]:
        rows = []
        for q, plan, vec in zip(queries, plans, vectors):
            hard = plan['hard']
            text_hits, rare_hits, rescue = text_for(conn, q['text'], plan)
            vec_hits = vector_for(client, args.collection, vec, plan)
            vec_full = base.hydrate_vector_hits(conn, vec_hits)
            if group_key == 'T':
                hits = text_hits
            elif group_key == 'V':
                hits = vec_full
            else:
                if rescue:
                    hits = hr.rrf_fuse([text_hits, vec_full, rare_hits], weights=[1.0, 1.0, 3.0])
                else:
                    hits = hr.rrf_fuse([text_hits, vec_full])
                if group_key == 'HR':
                    candidates = hits[: hr.CONFIG['rerank_candidates']]
                    docs = [hr.embedding_text(h)[: hr.CONFIG['rerank_doc_chars']] for h in candidates]
                    scores, _ = qwen_api.rerank(q['text'], docs)
                    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
                    hits = []
                    for h, score in ranked:
                        item = dict(h)
                        item['rerank_score'] = score
                        hits.append(item)
            row = base.judge(hits, q)
            hard_hits = hits[:base.K] if hard else []
            compliant = [hit_complies(h, hard) for h in hard_hits]
            row.update({
                'hard_filters': hard,
                'compliant_hits': sum(1 for c in compliant if c),
                'compliant_ratio': (sum(1 for c in compliant if c) / len(compliant)) if compliant else 0.0,
                'all_compliant': bool(hard) and bool(hard_hits) and all(compliant),
            })
            rows.append(row)
        return rows

    groups = {}
    for key in ('T', 'V', 'H', 'HR'):
        t0 = time.perf_counter()
        groups[key] = {'seconds': round(time.perf_counter() - t0, 2), **group(rows_for(key))}
        m = groups[key]['metrics']
        print(f"{key}: Recall={m['found']}/{m['queries']} strict={m['strict_found']}/{m['strict_queries']} "
              f"compliance={m['filter_compliance_rate']}")

    baseline = {}
    if BASELINE.exists():
        old = json.loads(BASELINE.read_text(encoding='utf-8'))
        for key in ('H', 'HR'):
            m = old['groups'][key]['metrics']
            baseline[key] = {'recall_at_8': m['recall_at_8'], 'strict_recall_at_8': m['strict_recall_at_8']}

    doc = {
        'dataset': {'path': args.dataset.relative_to(ROOT).as_posix(),
                    'sha256': __import__('hashlib').sha256(dataset_bytes).hexdigest(),
                    'queries': len(queries),
                    'strict_queries': sum(1 for q in queries if q['expect'].get('strict'))},
        'collection': args.collection,
        'plan_version': query_plan.PLAN_VERSION,
        'models': {'embedding': qwen_api.embedding_model(), 'reranker': qwen_api.rerank_model()},
        'query_embedding': embed_stats,
        'groups': groups,
        'plans': plans,
        'baseline': baseline,
        'elapsed_seconds': round(time.perf_counter() - started, 1),
        'git_commit': hr._git_commit(),
    }
    json_path = Path(str(args.out_prefix) + '.json')
    md_path = Path(str(args.out_prefix) + '.md')
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    md_path.write_text(render(doc), encoding='utf-8')
    conn.close()
    print(f'JSON: {json_path}')
    print(f'MD  : {md_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
