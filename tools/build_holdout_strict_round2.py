"""Build strict-candidate round 2 for 20 holdout queries (H+HR union)."""

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
EXISTING = ROOT / 'corpus/eval/teacher_questions.holdout120.strict_candidates.json'
QP = ROOT / 'var/retrieval/holdout120_qp_strict_2026-11-07.json'
OUT = ROOT / 'corpus/eval/teacher_questions.holdout120.strict_candidates_round2.json'


def main() -> int:
    dataset = json.loads(DATA.read_text(encoding='utf-8'))
    existing = json.loads(EXISTING.read_text(encoding='utf-8'))
    known = {r['id'] for r in existing['rows']}
    qp = json.loads(QP.read_text(encoding='utf-8'))
    h_rows = {r['id']: r for r in qp['groups']['H']['queries']}
    hr_rows = {r['id']: r for r in qp['groups']['HR']['queries']}
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for q in dataset['queries']:
        if q.get('strict_plan') and q['id'] not in known and 'strict' not in q.get('expect', {}):
            buckets[(q['source'], q['category'])].append(q)
    selected = []
    # Round-robin 3 per source/category bucket, up to 20.
    for key in sorted(buckets):
        selected.extend(buckets[key][:3])
    selected = selected[:20]
    dsn = (os.environ.get('CHILON_TEST_DATABASE_URL') or os.environ.get('CHILON_DATABASE_URL') or '')
    dsn = dsn.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn, connect_timeout=10) if dsn else None
    rows = []
    with conn.cursor() as cur:
        for q in selected:
            ids = []
            for mode, table in (('H', h_rows), ('HR', hr_rows)):
                for rank, cid in enumerate((table.get(q['id']) or {}).get('top_ids', [])[:5], 1):
                    ids.append((cid, mode, rank))
            seen = set()
            candidates = []
            for cid, mode, rank in ids:
                if cid in seen:
                    continue
                seen.add(cid)
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
                                       'excerpt': (r[1] or '')[:280], 'mode': mode, 'rank': rank})
            rows.append({'id': q['id'], 'category': q['category'], 'source': q['source'],
                         'query': q['text'], 'strict_plan': q['strict_plan'],
                         'terms': q.get('terms') or [], 'candidates': candidates})
    if conn:
        conn.close()
    OUT.write_text(json.dumps({'count': len(rows), 'rows': rows}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('wrote', OUT, 'queries', len(rows), 'candidates', sum(len(r['candidates']) for r in rows))
    print('ids', [r['id'] for r in rows])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
