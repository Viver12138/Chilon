"""Apply round-3 teacher-selected holdout strict gold (13 selected / 2 no-gold)."""

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

REVIEW = ROOT / 'review_sheets/filled/strict复核_11.7 22.37.txt'
DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
GOLD = ROOT / 'corpus/eval/teacher_questions.holdout120.gold.json'
MANIFEST = ROOT / 'corpus/eval/teacher_questions.holdout120.manifest.json'


def parse_selected(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 7 or cells[0] in ('组号', '---') or set(cells[0]) <= set('-:'):
            continue
        qid = cells[1]
        ids = [x.strip() for x in re.split(r'[；;]', cells[4]) if x.strip() and x.strip() != '—']
        if ids:
            out[qid] = {'chunk_ids': ids, 'note': cells[6]}
    return out


def main() -> int:
    selected = parse_selected(REVIEW)
    dataset = json.loads(DATA.read_text(encoding='utf-8'))
    gold_doc = json.loads(GOLD.read_text(encoding='utf-8'))
    existing_rows = gold_doc.get('rows', [])
    existing_chunks = {(r['query_id'], r['chunk_id']) for r in existing_rows}
    dsn = (os.environ.get('CHILON_TEST_DATABASE_URL') or os.environ.get('CHILON_DATABASE_URL') or '')
    dsn = dsn.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn, connect_timeout=10) if dsn else None
    added = []
    with conn.cursor() as cur:
        for q in dataset['queries']:
            sel = selected.get(q['id'])
            if not sel:
                continue
            q['expect']['strict'] = {
                'chunk_ids': sel['chunk_ids'],
                'object_type': q.get('strict_plan') or 'any',
                'rationale': f'holdout strict round3 teacher selection: {sel["note"]}',
                'verified_by': ['T-HOLDOUT-R3'],
                'verified_at': '2026-11-07',
            }
            q['review_status'] = 'strict_reviewed'
            for idx, cid in enumerate(sel['chunk_ids'], 1):
                if (q['id'], cid) in existing_chunks:
                    continue
                cur.execute("""
                    SELECT c.id::text, c.text_content, s.title, c.locator::text
                    FROM knowledge_chunks c
                    JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
                    JOIN knowledge_sources s ON s.id = dv.source_id
                    WHERE c.id = %s::uuid
                """, (cid,))
                r = cur.fetchone()
                if not r:
                    raise SystemExit(f'missing chunk {cid} for {q["id"]}')
                added.append({
                    'query_id': q['id'], 'category': q['category'], 'text': q['text'],
                    'object_type': q.get('strict_plan') or 'any', 'gold_index': idx,
                    'chunk_id': r[0], 'title': r[2], 'locator': r[3],
                    'excerpt': (r[1] or '')[:600], 'rationale': sel['note'],
                })
                existing_chunks.add((q['id'], cid))
    if conn:
        conn.close()
    all_rows = existing_rows + added
    dataset['strict_count'] = sum(1 for q in dataset['queries'] if q.get('expect', {}).get('strict'))
    dataset['strict_review'] = dataset.get('strict_review') or {}
    dataset['strict_review'].update({
        'round3_source': str(REVIEW.relative_to(ROOT)).replace('\\', '/'),
        'round3_queries': len(selected), 'round3_chunks_added': len(added),
        'total_strict_queries': dataset['strict_count'], 'total_chunks': len(all_rows),
    })
    DATA.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    GOLD.write_text(json.dumps({
        'version': 'teacher-questions/holdout120-gold-v3',
        'query_count': dataset['strict_count'],
        'chunk_rows': len(all_rows),
        'note': 'holdout strict expanded to >=30 by round3; still not full 120 strict.',
        'rows': all_rows,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    manifest.update({
        'strict_count': dataset['strict_count'], 'strict_review': dataset['strict_review'],
        'sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(), 'gold': GOLD.name,
    })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'round3 selected={len(selected)} added_chunks={len(added)} total_strict={dataset["strict_count"]} total_chunks={len(all_rows)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
