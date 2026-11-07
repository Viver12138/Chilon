"""Pre-release smoke: 20 representative queries through hybrid H.

Checks:
  * no exceptions;
  * every hit has the fields downstream needs;
  * empty rate <= 5%;
  * P95 latency <= 8s.

This is a plumbing/latency smoke, not a quality eval (use holdout120 for quality).

    .\\.venv\\Scripts\\python.exe tools\\release_smoke.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

DATASET = ROOT / 'corpus/eval/teacher_questions.v2.json'
REQUIRED = {'chunk_id', 'excerpt', 'source_title', 'source_type', 'rank'}


def main() -> int:
    from app.services import routed_retrieval

    doc = json.loads(DATASET.read_text(encoding='utf-8'))
    by_cat = {}
    for q in doc['queries']:
        by_cat.setdefault(q['category'], []).append(q)
    queries = []
    for cat in ('主题词', '题型+知识点', '教材概念', '年份+卷别', '自然语言要求'):
        queries.extend(by_cat.get(cat, [])[:4])
    queries = queries[:20]
    print(f'queries={len(queries)} mode=hybrid_h')
    latencies = []
    empty = 0
    failures = []
    for q in queries:
        started = time.perf_counter()
        try:
            result = routed_retrieval.search(q['text'], limit=8, mode='h', user_key='release-smoke')
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{q['id']}: exception {type(exc).__name__}: {exc}")
            continue
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        if not result['hits']:
            empty += 1
            failures.append(f"{q['id']}: empty ({result.get('empty_reason')})")
        for hit in result['hits']:
            missing = REQUIRED - set(hit)
            if missing:
                failures.append(f"{q['id']}: hit missing {sorted(missing)}")
                break
        print(f"  {q['id']} {result['status']:5s} hits={len(result['hits'])} {elapsed:.0f}ms")
    p95 = sorted(latencies)[max(0, int(round((len(latencies) - 1) * 0.95)))] if latencies else None
    empty_rate = empty / len(queries) if queries else 0
    print(f'empty={empty}/{len(queries)} ({empty_rate:.1%}) p95={p95:.0f}ms ' if p95 else f'empty={empty}/{len(queries)}')
    if empty_rate > 0.05:
        failures.append(f'empty rate {empty_rate:.1%} > 5%')
    if p95 is not None and p95 > 8000:
        failures.append(f'p95 {p95:.0f}ms > 8000ms')
    if failures:
        print('FAIL:')
        for failure in failures[:20]:
            print(' -', failure)
        return 1
    print('PASS: release smoke')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
