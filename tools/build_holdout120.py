"""Build a 120-query holdout set from the two unused teacher collections.

Sources:
  * 教师问题收集_v2.0_高一教师填写.xlsx (60)
  * 教师问题收集_v2.0_高二教师填写.xlsx (60)

For each query, qwen-plus extracts 3-5 retrieval terms (Chinese text -> qwen-plus
policy). The resulting expectations are DRAFT: a teacher must review them before
the holdout can be used as a strict/lenient benchmark.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))
import qwen_api  # noqa: E402

POOL = ROOT / 'var/eval_v2/candidates_pool.json'
OUT = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
MANIFEST = ROOT / 'corpus/eval/teacher_questions.holdout120.manifest.json'
SOURCES = [
    ('教师问题收集_v2.0_高一教师填写.xlsx', 'G1'),
    ('教师问题收集_v2.0_高二教师填写.xlsx', 'G2'),
]
URL = qwen_api.chat_base_url() + '/chat/completions'

PROMPT = """你是高中数学检索评测助手。给每条教师问题抽取 3-5 个用于检索教材/题目的规范关键词或短语（中文），要求：
- 优先包含学科术语（如“二面角”“点斜式方程”“等差数列”）；
- 不要包含“怎么求/有哪些/请/帮我/题目”等泛词；
- 不要解释。
只输出 JSON 数组，每项 {"id": "...", "terms": ["...", "..."]}。"""


def extract_terms(queries: list[dict], batch: int = 20) -> tuple[dict[str, list[str]], dict]:
    result: dict[str, list[str]] = {}
    usage = {'requests': 0, 'prompt_tokens': 0, 'completion_tokens': 0, 'seconds': 0.0}
    for start in range(0, len(queries), batch):
        chunk = queries[start:start + batch]
        lines = '\n'.join(json.dumps({'id': q['id'], 'query': q['text']}, ensure_ascii=False) for q in chunk)
        payload = {
            'model': qwen_api.chat_model(),
            'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': lines}],
            'temperature': 0,
            'max_tokens': 1500,
        }
        t0 = time.perf_counter()
        with httpx.Client(timeout=120) as client:
            response = client.post(URL, headers={'Authorization': f'Bearer {qwen_api._api_key()}'}, json=payload)
        response.raise_for_status()
        body = response.json()
        u = body.get('usage') or {}
        usage['requests'] += 1
        usage['prompt_tokens'] += int(u.get('prompt_tokens') or 0)
        usage['completion_tokens'] += int(u.get('completion_tokens') or 0)
        usage['seconds'] = round(usage['seconds'] + time.perf_counter() - t0, 1)
        text = body['choices'][0]['message']['content'].strip()
        text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        start_i, end_i = text.find('['), text.rfind(']')
        if start_i < 0 or end_i < 0:
            print(f'  batch {start}: no JSON; fallback', flush=True)
            continue
        try:
            parsed = json.loads(text[start_i:end_i + 1])
        except json.JSONDecodeError:
            print(f'  batch {start}: bad JSON; fallback', flush=True)
            continue
        for item in parsed:
            qid = item.get('id')
            terms = [str(t).strip() for t in (item.get('terms') or []) if str(t).strip()]
            if qid and terms:
                result[qid] = terms[:6]
        print(f'  {min(start + batch, len(queries))}/{len(queries)}', flush=True)
    return result, usage


def main() -> int:
    parser = argparse.ArgumentParser(description='Build 120-query holdout draft')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args()
    pool = json.loads(POOL.read_text(encoding='utf-8'))['questions']
    selected = []
    for source, tag in SOURCES:
        qs = [q for q in pool if q['source'] == source]
        if len(qs) != 60:
            raise SystemExit(f'{source}: expected 60, got {len(qs)}')
        for q in qs:
            selected.append({
                'id': f'HO-{tag}-{q["id"]}',
                'text': q['text'],
                'category': q['category'],
                'source': source,
                'contributor': q.get('contributor'),
                'strict_plan': q.get('strict_plan') or '',
                'expect_any_raw': q.get('expect_any_raw') or '',
                'notes': 'holdout draft; terms from qwen-plus, teacher review required',
            })
    terms, usage = extract_terms(selected)
    # Backfill deterministic keywords for any missed batch.
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.services import hybrid_retrieval as hr  # noqa: E402

    missing = 0
    for q in selected:
        qterms = terms.get(q['id'])
        if not qterms:
            qterms = list(hr.extract_conditions(q['text'])['keywords'])[:5] or [q['text'][:12]]
            missing += 1
        q['expect'] = {
            'any': [{'field': 'text', 'contains': term} for term in qterms],
            'reason': 'qwen-plus term extraction (draft); teacher review required',
        }
        q['terms'] = qterms
        q['review_status'] = 'draft_terms'
    doc = {
        'version': 'teacher-questions/holdout120-draft',
        'dataset': 'holdout120',
        'created_at': '2026-11-07',
        'sources': [s for s, _ in SOURCES],
        'count': len(selected),
        'strict_count': 0,
        'note': '120 条未参与 v2 调参的教师问题；期望词由 qwen-plus 抽取，尚未教师复核；strict 待补。',
        'term_extraction': {'model': qwen_api.chat_model(), 'usage': usage, 'fallback_queries': missing},
        'queries': selected,
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'dataset': args.out.name,
        'count': len(selected),
        'strict_count': 0,
        'categories': dict(Counter(q['category'] for q in selected)),
        'sources': dict(Counter(q['source'] for q in selected)),
        'review_status': 'draft_terms',
        'term_extraction_usage': usage,
        'note': '教师复核期望词后才能用于 holdout 评测；strict 尚未标注。',
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {args.out} ({len(selected)} queries), {args.manifest}')
    print('categories', manifest['categories'])
    print('fallback', missing, 'usage', usage)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
