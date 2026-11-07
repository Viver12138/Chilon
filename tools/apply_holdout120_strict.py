"""Apply teacher-selected strict gold for the 12 holdout candidates.

Filled file: review_sheets/filled/strict回填.txt
Only selected chunk_ids become strict gold; the other 6 queries stay any-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))
import psycopg  # noqa: E402

REVIEW = ROOT / 'review_sheets/filled/strict回填.txt'
DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
GOLD = ROOT / 'corpus/eval/teacher_questions.holdout120.gold.json'
MANIFEST = ROOT / 'corpus/eval/teacher_questions.holdout120.manifest.json'


def parse_selected(path: Path) -> dict[str, dict]:
    out = {}
    in_summary = False
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('## 选中汇总'):
            in_summary = True
            continue
        if in_summary and line.startswith('## '):
            break
        if not in_summary or not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 6 or cells[0] in ('序号', '---') or set(cells[0]) <= set('-:'):
            continue
        qid = cells[1]
        ids = [x.strip() for x in re.split(r'[；;]', cells[4]) if x.strip() and x.strip() != '—']
        if ids:
            out[qid] = {'strict_plan': cells[2], 'chunk_ids': ids, 'note': cells[5]}
    return out


def main() -> int:
    selected = parse_selected(REVIEW)
    dataset = json.loads(DATA.read_text(encoding='utf-8'))
    dsn = (os.environ.get('CHILON_TEST_DATABASE_URL') or os.environ.get('CHILON_DATABASE_URL') or '')
    dsn = dsn.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn, connect_timeout=10) if dsn else None
    gold_rows = []
    with conn.cursor() as cur:
        for q in dataset['queries']:
            sel = selected.get(q['id'])
            if not sel:
                continue
            q['expect']['strict'] = {
                'chunk_ids': sel['chunk_ids'],
                'object_type': sel['strict_plan'],
                'rationale': f"holdout strict candidate teacher selection: {sel['note']}",
                'verified_by': ['T-HOLDOUT'],
                'verified_at': '2026-11-07',
            }
            q['review_status'] = 'strict_reviewed'
            q['notes'] = 'holdout; terms + strict teacher-reviewed'
            for idx, cid in enumerate(sel['chunk_ids'], 1):
                cur.execute("""
                    SELECT c.id::text, c.text_content, s.title, c.locator::text
                    FROM knowledge_chunks c
                    JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
                    JOIN knowledge_sources s ON s.id=dv.source_id
                    WHERE c.id=%s::uuid
                """, (cid,))
                r = cur.fetchone()
                if not r:
                    raise SystemExit(f'missing chunk {cid} for {q["id"]}')
                gold_rows.append({
                    'query_id': q['id'], 'category': q['category'], 'text': q['text'],
                    'object_type': sel['strict_plan'], 'gold_index': idx,
                    'chunk_id': r[0], 'title': r[2], 'locator': r[3],
                    'excerpt': (r[1] or '')[:600], 'rationale': sel['note'],
                })
    if conn:
        conn.close()
    dataset['strict_count'] = len(selected)
    dataset['review_status'] = 'strict_reviewed'
    dataset['strict_review'] = {
        'source': str(REVIEW.relative_to(ROOT)).replace('\\', '/'),
        'queries': len(selected), 'chunks': len(gold_rows), 'reviewed_at': '2026-11-07',
        'note': '只覆盖 12 条 strict 候选中的 6 条；其余 108 条未导候选，strict 不完整。',
    }
    DATA.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    GOLD.write_text(json.dumps({
        'version': 'teacher-questions/holdout120-gold-draft',
        'query_count': len({r['query_id'] for r in gold_rows}),
        'chunk_rows': len(gold_rows),
        'note': 'holdout strict pilot: only 6/120 queries have strict gold; not a full holdout set.',
        'rows': gold_rows,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    manifest.update({
        'strict_count': len(selected),
        'strict_review': dataset['strict_review'],
        'review_status': 'strict_reviewed',
        'sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(),
        'gold': GOLD.name,
    })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('strict queries', len(selected), 'chunks', len(gold_rows))
    for q, s in selected.items():
        print(' ', q, s['chunk_ids'])
    print('wrote', DATA, GOLD, MANIFEST)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
