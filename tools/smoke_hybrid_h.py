"""Smoke test for the hybrid H retrieval path (no H/HR routing).

Requires CHILON_DATABASE_URL, QDRANT_URL and the Qwen key in .env.

    .\\.venv\\Scripts\\python.exe tools\\smoke_hybrid_h.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))


def main() -> int:
    parser = argparse.ArgumentParser(description='Smoke-test hybrid H retrieval')
    parser.add_argument('--query', default='导数的切线方程公式是什么？')
    parser.add_argument('--limit', type=int, default=3)
    args = parser.parse_args()
    from app.services import routed_retrieval

    result = routed_retrieval.search(args.query, limit=args.limit, mode='h', user_key='smoke')
    print('mode', result['mode'], 'status', result.get('status'), 'hits', len(result['hits']), 'ms', result['elapsed_ms'])
    for hit in result['hits']:
        print(' ', hit['rank'], hit['chunk_id'][:8], hit.get('source_type'), (hit.get('excerpt') or '')[:60].replace('\n', ' '))
    if not result['hits']:
        print('FAIL: hybrid H returned no hits')
        return 1
    expected = {'chunk_id', 'excerpt', 'source_title', 'source_type', 'rank'}
    missing = expected - set(result['hits'][0])
    if missing:
        print(f'FAIL: hit missing fields {sorted(missing)}')
        return 1
    print('PASS: hybrid H smoke')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
