"""Post-hoc H/HR router evaluation from a QueryPlan P0 run.

Policy (interim, 2026-11-07 decision memo):
  * formula_search / knowledge_search -> HR (precise lookup)
  * everything else -> H (coverage default)

The H and HR rows come from the same QP run (same plans/hard filters), so this is
a reproducible post-hoc routing analysis, not a re-retrieval.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\eval_v2_router.py `
        --qp-json var/retrieval/v2_eval_qp_2026-11-07.json `
        --out-prefix var/retrieval/v2_eval_router_2026-11-07
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))

from app.services import query_plan  # noqa: E402
import eval_v2 as base  # noqa: E402


def category_table(rows: list[dict]) -> dict:
    out = {}
    for cat in ('主题词', '题型+知识点', '教材概念', '年份+卷别', '自然语言要求'):
        subset = [r for r in rows if r['category'] == cat]
        if subset:
            m = base.metrics(subset)
            out[cat] = {k: m[k] for k in ('found', 'queries', 'strict_found', 'strict_queries',
                                           'strict_recall_at_8', 'strict_mrr_at_8')}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='H/HR routed evaluation')
    parser.add_argument('--qp-json', type=Path, required=True)
    parser.add_argument('--out-prefix', type=Path, default=ROOT / 'var/retrieval/v2_eval_router_2026-11-07')
    args = parser.parse_args()
    doc = json.loads(args.qp_json.read_text(encoding='utf-8'))
    h_rows = {q['id']: q for q in doc['groups']['H']['queries']}
    hr_rows = {q['id']: q for q in doc['groups']['HR']['queries']}
    routed = []
    decisions = []
    for qid, h in h_rows.items():
        plan = query_plan.build_plan(h['text'])
        mode = query_plan.preferred_mode(plan)
        chosen = hr_rows[qid] if mode == 'HR' else h
        routed.append(chosen)
        decisions.append({'id': qid, 'text': h['text'], 'intent': plan['intent'],
                          'mode': mode, 'hard': plan['hard']})
    metrics = base.metrics(routed)
    payload = {
        'version': 'h-hr-router/v0',
        'source': str(args.qp_json),
        'policy': 'formula_search/knowledge_search -> HR; question/mixed -> H',
        'dataset': doc.get('dataset'),
        'collection': doc.get('collection'),
        'models': doc.get('models'),
        'retrieval_config': {
            'final_k': base.K,
            'rerank_candidates': hr_rows and doc.get('retrieval_config', {}).get('rerank_candidates'),
            'query_plan_version': query_plan.PLAN_VERSION,
            'hard_filter_mode': 'strict (no fallback)',
        },
        'mode_counts': dict(Counter(d['mode'] for d in decisions)),
        'metrics': metrics,
        'by_category': category_table(routed),
        'mode_decisions': decisions,
        'rows': routed,
    }
    # Pull candidate_k from the QP eval metadata when available.
    payload['retrieval_config']['rerank_candidates'] = doc.get('retrieval_config', {}).get('candidate_k', 30)
    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(str(args.out_prefix) + '.json')
    md_path = Path(str(args.out_prefix) + '.md')
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def pct(x):
        return '—' if x is None else f'{x:.1%}'

    lines = ['# H/HR 路由评测（post-hoc）', '',
             f"- 来源：`{args.qp_json}`",
             f"- 策略：formula/knowledge → HR；question/mixed → H",
             f"- 模式分布：{payload['mode_counts']}",
             f"- 配置：final_k={base.K}，candidate_k={payload['retrieval_config']['rerank_candidates']}，QueryPlan={query_plan.PLAN_VERSION}", '',
             '## 指标', '',
             '| 指标 | 值 |', '| --- | ---: |',
             f"| Recall@8 | {metrics['found']}/{metrics['queries']} = {pct(metrics['recall_at_8'])} |",
             f"| Strict Recall@8 | {metrics['strict_found']}/{metrics['strict_queries']} = {pct(metrics['strict_recall_at_8'])} |",
             f"| Strict MRR@8 | {metrics['strict_mrr_at_8']:.3f} |",
             f"| Strict@1 | {pct(metrics['strict_at_1'])} |",
             f"| Strict-all@8 | {pct(metrics['strict_all_at_8'])} |", '',
             '## 分类别', '',
             '| 类别 | Recall | Strict Recall | Strict MRR |', '| --- | ---: | ---: | ---: |']
    for cat, m in payload['by_category'].items():
        smrr = '—' if m['strict_mrr_at_8'] is None else f"{m['strict_mrr_at_8']:.3f}"
        lines.append(f"| {cat} | {pct(m['found']/m['queries'])} | {pct(m['strict_recall_at_8'])} | {smrr} |")
    lines += ['', '## 路由决策', '', '| query | intent | mode |', '| --- | --- | --- |']
    for d in decisions:
        lines.append(f"| {d['text']} | {d['intent']} | **{d['mode']}** |")
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"routed Recall={metrics['found']}/{metrics['queries']} strict={metrics['strict_found']}/{metrics['strict_queries']} "
          f"strictMRR={metrics['strict_mrr_at_8']:.3f} modes={payload['mode_counts']}")
    print('JSON', json_path)
    print('MD  ', md_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
