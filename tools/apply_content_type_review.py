"""Apply the filled content_type review Markdown to the rule draft.

Input:  review_sheets/filled/教材内容类型标注复核_已填.md
        var/textbook_mapping/textbook_content_type_draft.json
Output: corpus/textbook/content_type_reviewed_120_2026-11-07.json
        var/textbook_mapping/content_type_draft_with_review.json

The reviewed 120 rows use the teacher label as `primary`; the remaining blocks
keep the rule label and stay `review_status=draft` (not a frozen annotation).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MD = ROOT / 'review_sheets/filled/教材内容类型标注复核_已填.md'
DEFAULT_DRAFT = ROOT / 'var/textbook_mapping/textbook_content_type_draft.json'
DEFAULT_OUT = ROOT / 'corpus/textbook/content_type_reviewed_120_2026-11-07.json'
DEFAULT_OVERLAY = ROOT / 'var/textbook_mapping/content_type_draft_with_review.json'


def parse_md(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 6 or cells[0] in ('序号', '---') or set(cells[0]) <= set('-:'):
            continue
        labels = [x.strip() for x in cells[4].replace('，', ',').split(',') if x.strip() and x.strip() != '—']
        rows.append({
            'seq': int(cells[0]),
            'block_id': cells[1],
            'rule_primary': cells[2],
            'teacher_primary': cells[3],
            'teacher_labels': labels,
            'note': cells[5],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply filled content_type review')
    parser.add_argument('--review-md', type=Path, default=DEFAULT_MD)
    parser.add_argument('--draft', type=Path, default=DEFAULT_DRAFT)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--overlay', type=Path, default=DEFAULT_OVERLAY)
    args = parser.parse_args()

    reviewed = parse_md(args.review_md)
    draft = json.loads(args.draft.read_text(encoding='utf-8'))
    by_block = {b['block_id']: b for b in draft['blocks']}
    missing = [r['block_id'] for r in reviewed if r['block_id'] not in by_block]
    if missing:
        print(f'ERROR: {len(missing)} reviewed block_ids not in draft: {missing[:10]}')
        return 3
    agree = sum(1 for r in reviewed if r['rule_primary'] == r['teacher_primary'])
    confusion = Counter((r['rule_primary'], r['teacher_primary']) for r in reviewed if r['rule_primary'] != r['teacher_primary'])
    out = {
        'version': 'content-type-reviewed/v0',
        'date': str(date.today()),
        'source': 'review_sheets/filled/教材内容类型标注复核_已填.md',
        'enum': draft['enum'],
        'reviewed_count': len(reviewed),
        'rule_agree': agree,
        'rule_agreement_rate': round(agree / len(reviewed), 4),
        'mismatch_pairs': {f'{a}->{b}': n for (a, b), n in confusion.most_common()},
        'status': 'pilot-reviewed-120; full 1797 NOT frozen',
        'rows': reviewed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # Overlay: teacher labels for reviewed blocks, rule labels for the rest.
    for row in reviewed:
        block = by_block[row['block_id']]
        block['rule_primary'] = block['primary']
        block['primary'] = row['teacher_primary']
        block['labels'] = [row['teacher_primary'], *row['teacher_labels']]
        block['method'] = 'teacher'
        block['review_status'] = 'reviewed'
        block['teacher_note'] = row['note']
    for block in draft['blocks']:
        block.setdefault('review_status', 'draft')
    overlay = dict(draft)
    overlay['note'] = '120 条教师复核覆盖 + 1677 条 rule-v0 draft；不是全量冻结标注。'
    overlay['review'] = {
        'reviewed': len(reviewed),
        'rule_agree': agree,
        'rule_agreement_rate': round(agree / len(reviewed), 4),
        'mismatch_pairs': out['mismatch_pairs'],
    }
    overlay['counts_with_review'] = dict(Counter(b['primary'] for b in overlay['blocks']))
    args.overlay.write_text(json.dumps(overlay, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'reviewed={len(reviewed)} rule_agree={agree} ({agree/len(reviewed):.1%})')
    print('mismatch_pairs:', out['mismatch_pairs'])
    print('wrote', args.out, args.overlay)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
