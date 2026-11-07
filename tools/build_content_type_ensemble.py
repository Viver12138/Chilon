"""Build the rule+LLM content_type ensemble over all 1797 blocks.

High confidence = rule-v0 primary == LLM primary.  Everything else is
needs_review; no content_type is assigned to disagreements.

Inputs:
  var/textbook_mapping/textbook_content_type_draft.json
  var/textbook_mapping/content_type_llm_all.json
  corpus/textbook/content_type_reviewed_120_2026-11-07.json
Outputs:
  var/textbook_mapping/content_type_ensemble.json
  corpus/textbook/content_type_ensemble_summary_2026-11-07.json
  var/textbook_mapping/content_type_ensemble_review_sample.json
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / 'var/textbook_mapping/textbook_content_type_draft.json'
LLM = ROOT / 'var/textbook_mapping/content_type_llm_all.json'
REVIEW = ROOT / 'corpus/textbook/content_type_reviewed_120_2026-11-07.json'
OUT = ROOT / 'var/textbook_mapping/content_type_ensemble.json'
SUMMARY = ROOT / 'corpus/textbook/content_type_ensemble_summary_2026-11-07.json'
HIGH_OUT = ROOT / 'corpus/textbook/content_type_ensemble_high_confidence_2026-11-07.json'
SAMPLE = ROOT / 'var/textbook_mapping/content_type_ensemble_review_sample.json'
TYPES = ('definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other')


def main() -> int:
    draft = json.loads(DRAFT.read_text(encoding='utf-8'))
    llm_doc = json.loads(LLM.read_text(encoding='utf-8'))
    llm = llm_doc['labels']
    review = json.loads(REVIEW.read_text(encoding='utf-8'))
    teacher = {r['block_id']: r['teacher_primary'] for r in review['rows']}

    rows = []
    for block in draft['blocks']:
        rule = block['primary']
        item = llm.get(block['block_id'])
        row = {
            'block_id': block['block_id'],
            'chunk_id': block['chunk_id'],
            'source_title': block['source_title'],
            'page': block['page'],
            'text_excerpt': (block.get('text_excerpt') or block['text'])[:500],
            'rule_primary': rule,
            'llm_primary': item['primary'] if item else None,
            'llm_confidence': item.get('confidence') if item else None,
            'teacher_primary': teacher.get(block['block_id']),
        }
        if item and item['primary'] == rule:
            row.update({'primary': rule, 'labels': sorted({rule, *(item.get('labels') or [])}),
                        'status': 'high_confidence', 'method': 'ensemble-agree'})
        else:
            row.update({'primary': None, 'labels': [],
                        'status': 'needs_review',
                        'method': 'ensemble-disagree' if item else 'llm-missing'})
        rows.append(row)

    high = [r for r in rows if r['status'] == 'high_confidence']
    reviewed = [r for r in high if r['teacher_primary']]
    acc = sum(1 for r in reviewed if r['primary'] == r['teacher_primary'])
    by_class = {}
    for cls in TYPES:
        total = [r for r in rows if r['teacher_primary'] == cls]
        covered = [r for r in high if r['teacher_primary'] == cls]
        if total:
            by_class[cls] = {'reviewed': len(total), 'high_confidence': len(covered),
                             'coverage': round(len(covered) / len(total), 4)}
    doc = {
        'version': 'content-type-ensemble/v1',
        'date': '2026-11-07',
        'rule': 'rule-v0',
        'llm': {'model': llm_doc.get('model'), 'scope': llm_doc.get('scope'), 'count': llm_doc.get('count')},
        'principle': 'only rule==LLM agreement gets content_type; disagreement -> needs_review',
        'total': len(rows),
        'high_confidence': len(high),
        'high_confidence_rate': round(len(high) / len(rows), 4),
        'needs_review': len(rows) - len(high),
        'validated_on_reviewed_120': len(reviewed),
        'validated_accuracy': round(acc / len(reviewed), 4) if reviewed else None,
        'high_by_class': dict(Counter(r['primary'] for r in high)),
        'coverage_by_teacher_class': by_class,
        'usage': llm_doc.get('usage'),
        'rows': rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    summary = {k: v for k, v in doc.items() if k not in ('rows', 'text_excerpt')}
    summary['note'] = '全量 1797 条 ensemble；只有一致子集赋 content_type；分歧仍需复核，禁止当正式标注。'
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    HIGH_OUT.write_text(json.dumps({
        'version': 'content-type-ensemble-high-confidence/v1',
        'date': '2026-11-07',
        'note': '仅 rule==LLM 一致子集；用于软信号试验，不是全量标注。',
        'count': len(high),
        'rows': [{'block_id': r['block_id'], 'chunk_id': r['chunk_id'], 'primary': r['primary'],
                  'labels': r['labels'], 'method': r['method']} for r in high],
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    rng = random.Random(44)
    by_book = defaultdict(list)
    for row in rows:
        if row['status'] == 'needs_review':
            by_book[row['source_title']].append(row)
    sample = []
    for title, items in sorted(by_book.items()):
        buckets = defaultdict(list)
        for row in items:
            buckets[row['rule_primary']].append(row)
        picked = []
        keys = sorted(buckets)
        while len(picked) < min(24, len(items)):
            progressed = False
            for key in keys:
                if buckets[key] and len(picked) < 24:
                    picked.append(buckets[key].pop(rng.randrange(len(buckets[key]))))
                    progressed = True
            if not progressed:
                break
        sample.extend(picked)
    SAMPLE.write_text(json.dumps({'version': 'content-type-ensemble-review/v1', 'count': len(sample), 'rows': sample},
                                 ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    print(f'total={len(rows)} high={len(high)} ({len(high)/len(rows):.1%}) '
          f'validated={len(reviewed)} acc={acc}/{len(reviewed)} '
          f'({acc/len(reviewed):.1%})' if reviewed else 'no validation')
    print('high_by_class', doc['high_by_class'])
    print('coverage_by_teacher_class', by_class)
    print('wrote', OUT, SUMMARY, SAMPLE, len(sample))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
