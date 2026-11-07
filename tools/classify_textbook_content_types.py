"""Draft content_type classification for the 1797 teacher-reviewed textbook blocks.

P0 data work: add a coarse content type (definition/theorem/formula/example/
exercise/catalog/reading/other) so retrieval can route formula/definition/theorem
queries to the right knowledge objects before content_type becomes a hard filter.

This tool only writes a **draft** (JSON/CSV + a stratified review sample); it does
not change PostgreSQL.  The review sample is what a teacher confirms before the
field is promoted.

Usage (from repo root, .venv interpreter):

    .\\.venv\\Scripts\\python.exe tools\\classify_textbook_content_types.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))

CONTENT_TYPES = ('definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other')

CATALOG_WORDS = ('目录', '本册导引', '小结', '知识结构', '章末小结')
READING_WORDS = ('阅读与思考', '探究与发现', '数学文化', '文献阅读', '阅读材料', '信息技术应用', '实习作业')
EXERCISE_WORDS = ('练习', '习题', '复习巩固', '综合运用', '拓广探索', '复习参考题')
EXAMPLE_RE = re.compile(r'例\s*\d+|例\s*[一二三四五六七八九十]|例题')
DEFINITION_WORDS = ('叫做', '称为', '定义为', '定义', '我们把', '一般地，设', '一般地，如果')
THEOREM_WORDS = ('定理', '性质', '判定', '推论', '基本事实')
FORMULA_WORDS = ('公式', '表达式', '通项', '即.', '由此得到')


def classify(text: str, title: str) -> dict:
    labels: list[str] = []
    if any(word in text for word in CATALOG_WORDS):
        labels.append('catalog')
    if any(word in text for word in READING_WORDS):
        labels.append('reading')
    if any(word in text for word in EXERCISE_WORDS):
        labels.append('exercise')
    if EXAMPLE_RE.search(text):
        labels.append('example')
    if any(word in text for word in DEFINITION_WORDS):
        labels.append('definition')
    if any(word in text for word in THEOREM_WORDS):
        labels.append('theorem')
    if any(word in text for word in FORMULA_WORDS):
        labels.append('formula')
    if not labels:
        labels.append('other')
    # Priority: catalog/reading are structural; exercise/example are page roles;
    # definition/theorem/formula are knowledge objects.
    priority = ['catalog', 'reading', 'exercise', 'example', 'definition', 'theorem', 'formula', 'other']
    primary = next(label for label in priority if label in labels)
    return {
        'primary': primary,
        'labels': labels,
        'mixed': len(labels) > 1,
        'confidence': 'explicit' if primary in labels and primary != 'other' else 'weak',
        'method': 'rule-v0',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Classify textbook blocks into content types (draft)')
    parser.add_argument('--database-url', default=os.environ.get('CHILON_TEST_DATABASE_URL'))
    parser.add_argument('--out', type=Path, default=ROOT / 'var/textbook_mapping/textbook_content_type_draft.json')
    parser.add_argument('--review-out', type=Path, default=ROOT / 'var/textbook_mapping/textbook_content_type_review_sample.json')
    parser.add_argument('--per-book', type=int, default=24, help='review sample per textbook')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    if not args.database_url:
        print('CHILON_TEST_DATABASE_URL is not set (or pass --database-url)', file=sys.stderr)
        return 2

    from app.services import hybrid_retrieval as hr

    import psycopg

    dsn = args.database_url.replace('postgresql+psycopg://', 'postgresql://')
    conn = psycopg.connect(dsn, connect_timeout=10)
    rows = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.block_id, a.chunk_id::text, c.text_content, s.title,
                   (c.locator->>'page')::int, a.kp_primary, a.module_id
            FROM textbook_block_annotations a
            JOIN knowledge_chunks c ON c.id = a.chunk_id
            JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
            JOIN knowledge_sources s ON s.id = dv.source_id
            WHERE a.superseded_by IS NULL AND s.source_type = 'textbook'
            ORDER BY s.title, (c.locator->>'page')::int, c.ordinal
        """)
        for r in cur.fetchall():
            rows.append({
                'block_id': r[0],
                'chunk_id': r[1],
                'text': r[2],
                'source_title': r[3],
                'page': r[4],
                'kp_primary': r[5],
                'module_id': r[6],
            })
    conn.close()
    if not rows:
        print('no textbook blocks found', file=sys.stderr)
        return 3

    for row in rows:
        result = classify(row['text'], row['source_title'])
        row.update(result)
        row['text_excerpt'] = row['text'][:500]

    counts = Counter(row['primary'] for row in rows)
    mixed = sum(1 for row in rows if row['mixed'])
    print(f'blocks={len(rows)} mixed={mixed}')
    for label in CONTENT_TYPES:
        print(f'  {label:10s} {counts.get(label, 0)}')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        'version': 'content-type-draft/v0',
        'source': 'textbook_block_annotations (teacher-reviewed, active)',
        'enum': list(CONTENT_TYPES),
        'total': len(rows),
        'counts': dict(counts),
        'mixed': mixed,
        'note': 'rule-v0 draft; NOT a frozen annotation. Teacher review required before content_type routing.',
        'blocks': rows,
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    # Stratified review sample: per book, per primary type, deterministic seed.
    rng = random.Random(args.seed)
    by_book: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_book[row['source_title']].append(row)
    sample = []
    for title, items in sorted(by_book.items()):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for row in items:
            buckets[row['primary']].append(row)
        picked = []
        keys = sorted(buckets)
        while len(picked) < min(args.per_book, len(items)):
            progressed = False
            for key in keys:
                pool = buckets[key]
                if pool and len(picked) < args.per_book:
                    picked.append(pool.pop(rng.randrange(len(pool))))
                    progressed = True
            if not progressed:
                break
        sample.extend(picked)
    args.review_out.parent.mkdir(parents=True, exist_ok=True)
    args.review_out.write_text(json.dumps({
        'version': 'content-type-review/v0',
        'note': '教师/编辑逐条确认 primary content_type；填写 teacher_label 与 note。',
        'enum': list(CONTENT_TYPES),
        'counts': dict(Counter(row['primary'] for row in sample)),
        'rows': sample,
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    # Full CSV for spreadsheet inspection.
    csv_path = args.out.with_suffix('.csv')
    with csv_path.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['block_id', 'source_title', 'page', 'primary', 'labels', 'mixed', 'confidence',
                         'kp_primary', 'module_id', 'text_excerpt'])
        for row in rows:
            writer.writerow([row['block_id'], row['source_title'], row['page'], row['primary'],
                             '|'.join(row['labels']), row['mixed'], row['confidence'],
                             row['kp_primary'], row['module_id'], row['text_excerpt']])
    print('draft:', args.out)
    print('review sample:', args.review_out, len(sample))
    print('csv:', csv_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
