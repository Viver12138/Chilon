"""Analyze Qwen LLM + rule-v0 agreement on the 120 reviewed textbook blocks."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / 'corpus/textbook/content_type_reviewed_120_2026-11-07.json'
DRAFT = ROOT / 'var/textbook_mapping/textbook_content_type_draft.json'
LLM = ROOT / 'var/textbook_mapping/content_type_llm_reviewed.json'
OUT = ROOT / 'corpus/textbook/content_type_llm_ensemble_120_2026-11-07.json'


def main() -> int:
    review = json.loads(REVIEW.read_text(encoding='utf-8'))
    draft = json.loads(DRAFT.read_text(encoding='utf-8'))
    llm = json.loads(LLM.read_text(encoding='utf-8'))
    by = {b['block_id']: b for b in draft['blocks']}
    rows = []
    for r in review['rows']:
        block = by[r['block_id']]
        item = (llm.get('labels') or {}).get(r['block_id']) or {}
        rule = block['primary']
        llm_primary = item.get('primary')
        rows.append({
            'block_id': r['block_id'],
            'source_title': block['source_title'],
            'page': block['page'],
            'text_excerpt': block.get('text_excerpt', '')[:300],
            'rule_primary': rule,
            'llm_primary': llm_primary,
            'teacher_primary': r['teacher_primary'],
            'rule_correct': rule == r['teacher_primary'],
            'llm_correct': llm_primary == r['teacher_primary'],
            'ensemble_agree': bool(llm_primary and rule == llm_primary),
        })
    n = len(rows)
    rule_acc = sum(1 for x in rows if x['rule_correct'])
    llm_acc = sum(1 for x in rows if x['llm_correct'])
    high = [x for x in rows if x['ensemble_agree']]
    high_acc = sum(1 for x in high if x['rule_correct'])
    disagree = [x for x in rows if not x['ensemble_agree']]
    disagree_rule = sum(1 for x in disagree if x['rule_correct'])
    disagree_llm = sum(1 for x in disagree if x['llm_correct'])
    by_class = {}
    for cls in sorted({x['teacher_primary'] for x in rows}):
        total = [x for x in rows if x['teacher_primary'] == cls]
        covered = [x for x in high if x['teacher_primary'] == cls]
        by_class[cls] = {
            'total': len(total),
            'high_confidence': len(covered),
            'coverage': round(len(covered) / len(total), 4),
        }
    doc = {
        'version': 'content-type-llm-ensemble/v0',
        'date': '2026-11-07',
        'scope': '120 teacher-reviewed blocks (pilot)',
        'model': llm.get('model'),
        'metrics': {
            'rule_v0_accuracy': round(rule_acc / n, 4),
            'llm_accuracy': round(llm_acc / n, 4),
            'ensemble_high_confidence': len(high),
            'ensemble_coverage': round(len(high) / n, 4),
            'ensemble_accuracy_on_high_confidence': round(high_acc / len(high), 4) if high else None,
            'disagreement_count': len(disagree),
            'disagreement_rule_accuracy': round(disagree_rule / len(disagree), 4) if disagree else None,
            'disagreement_llm_accuracy': round(disagree_llm / len(disagree), 4) if disagree else None,
        },
        'coverage_by_teacher_class': by_class,
        'conclusion': 'rule==LLM agreement is a high-precision subset (60/60), but only 50% coverage; do not use content_type as a hard filter yet. Use agreement only as a soft signal; review disagreements with active learning.',
        'rows': rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(doc['metrics'], ensure_ascii=False, indent=2))
    print('coverage', by_class)
    print('wrote', OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
