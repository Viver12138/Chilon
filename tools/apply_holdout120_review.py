"""Apply the filled holdout120 term review to the holdout dataset."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / 'review_sheets/filled/期望词复核回填.txt'
DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
MANIFEST = ROOT / 'corpus/eval/teacher_questions.holdout120.manifest.json'


def parse_review(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 3 or cells[0] in ('序号', '---') or set(cells[0]) <= set('-:'):
            continue
        terms = [t.strip() for t in re.split(r'[；;]', cells[2]) if t.strip()]
        if cells[1] and terms:
            out[cells[1]] = terms
    return out


def main() -> int:
    terms_by_id = parse_review(REVIEW)
    doc = json.loads(DATA.read_text(encoding='utf-8'))
    missing = []
    for q in doc['queries']:
        terms = terms_by_id.get(q['id'])
        if not terms:
            missing.append(q['id'])
            continue
        q['terms'] = terms
        q['expect'] = {
            'any': [{'field': 'text', 'contains': term} for term in terms],
            'reason': 'teacher-reviewed terms (2026-11-07)',
        }
        q['review_status'] = 'terms_reviewed'
        q['notes'] = 'holdout; terms teacher-reviewed; strict still pending'
    doc['review_status'] = 'terms_reviewed'
    doc['term_review'] = {
        'source': str(REVIEW.relative_to(ROOT)).replace('\\', '/'),
        'reviewed_queries': len(terms_by_id),
        'missing': missing,
        'reviewed_at': '2026-11-07',
    }
    doc['note'] = '120 条 holdout；期望词已教师复核；strict 尚未标注。'
    DATA.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    manifest.update({
        'review_status': 'terms_reviewed',
        'term_review': doc['term_review'],
        'sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(),
        'note': '期望词已复核；strict 尚未标注，不能作为 strict 样本外结论。',
    })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'applied terms to {len(terms_by_id)} queries; missing={len(missing)}')
    if missing:
        print('missing ids', missing[:10])
    print('wrote', DATA, MANIFEST)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
