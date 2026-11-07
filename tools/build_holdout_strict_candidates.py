"""Pick 20 holdout strict-plan queries and their top-5 H candidates for review."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))
import psycopg  # noqa: E402

DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
QP = ROOT / 'var/retrieval/holdout120_qp_2026-11-07.json'
OUT = ROOT / 'corpus/eval/teacher_questions.holdout120.strict_candidates.json'


def main() -> int:
    dataset = json.loads(DATA.read_text(encoding='utf-8'))
    qp = json.loads(QP.read_text(encoding='utf-8'))
    h_rows = {r['id']: r for r in qp['groups']['H']['queries']}
    # 2 strict-plan queries per source+category => 20 total.
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for q in dataset['queries']:
        if q.get('strict_plan'):
            buckets[(q['source'], q['category'])].append(q)
    selected = []
    for key in sorted(buckets):
        selected.extend(buckets[key][:2])
    selected = selected[:20]
    dsn = (os.environ.get('CHILON_TEST_DATABASE_URL') or os.environ.get('CHILON_DATABASE_URL') or '')
    dsn = dsn.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn, connect_timeout=10) if dsn else None
    rows = []
    with conn.cursor() as cur:
        for q in selected:
            top_ids = (h_rows.get(q['id']) or {}).get('top_ids', [])[:5]
            candidates = []
            for cid in top_ids:
                cur.execute("""
                    SELECT c.id::text, c.text_content, s.title, c.locator::text
                    FROM knowledge_chunks c
                    JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
                    JOIN knowledge_sources s ON s.id=dv.source_id
                    WHERE c.id=%s::uuid
                """, (cid,))
                r = cur.fetchone()
                if r:
                    candidates.append({'chunk_id': r[0], 'title': r[2], 'locator': r[3],
                                       'excerpt': (r[1] or '')[:300]})
            rows.append({'id': q['id'], 'category': q['category'], 'source': q['source'],
                         'query': q['text'], 'strict_plan': q['strict_plan'],
                         'terms': q.get('terms') or [], 'candidates': candidates})
    if conn:
        conn.close()
    OUT.write_text(json.dumps({'count': len(rows), 'rows': rows}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('wrote', OUT, 'queries', len(rows), 'candidates', sum(len(r['candidates']) for r in rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
