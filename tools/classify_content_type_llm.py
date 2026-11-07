"""LLM-assisted content_type classification (Qwen chat, DashScope compatible mode).

Step 1 (this run): classify the 120 teacher-reviewed blocks and report accuracy.
If it beats the rule baseline, the same tool can classify all 1797 blocks for a
teacher review sample; it is NOT a frozen annotation by itself.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\classify_content_type_llm.py --reviewed-only
    .\\.venv\\Scripts\\python.exe tools\\classify_content_type_llm.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))
import qwen_api  # noqa: E402

DRAFT = ROOT / 'var/textbook_mapping/textbook_content_type_draft.json'
REVIEW = ROOT / 'corpus/textbook/content_type_reviewed_120_2026-11-07.json'
OUT_REVIEWED = ROOT / 'var/textbook_mapping/content_type_llm_reviewed.json'
OUT_ALL = ROOT / 'var/textbook_mapping/content_type_llm_all.json'
TYPES = ['definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other']
URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

SYSTEM = """你是高中数学教材内容标注专家。给每个教材块选一个主类型，并给出多标签。
类型（只能使用这些英文值）：
- definition: 定义/概念，如“叫做/称为/定义为”
- theorem: 定理/性质/判定/推论/基本事实/方法步骤
- formula: 公式/表达式/通项，主体是公式或公式推导
- example: 例题（含解答），通常有“例1/例2/例题”或“解：分析：”
- exercise: 练习/习题/复习题/编号习题，主体是待做的题
- catalog: 目录/本册导引/章末小结/知识结构/回顾与思考
- reading: 阅读与思考/探究与发现/数学文化/文献阅读/信息技术应用/数学探究
- other: 章首导引/过渡正文/版权页/无法归类
规则：
1) 一个块只选一个 primary；如果同时含多种类型，labels 里放全部。
2) 结构优先级：catalog/小结 > reading/阅读探究 > 编号练习/习题 > 例题 > 定义 > 定理/性质 > 公式 > other。
3) 没有“练习/习题”标题，但正文是 1./2./(1)/(2) 编号题、含“求/证明/判断/已知”的，判 exercise。
4) “例1/例2/例题”或例题解答续块（“解：/分析：/证明：+如图”）判 example，即使块里出现“练习”字样。
5) “第X章/章首导引/本册导引”且没有完整知识对象的判 other；若明确是“章末小结/回顾与思考”判 catalog。
6) 含“阅读与思考/探究与发现/数学文化/文献阅读/信息技术应用/数学探究”的栏目判 reading，即使夹带习题。
7) “性质/判定/方法步骤/基本事实”的主体判 theorem；只有“叫做/称为/定义为”的主体判 definition。
8) 不要按单个关键词机械判断，要看整块主要角色。
只输出 JSON 数组，每项 {"block_id": "...", "primary": "...", "labels": ["..."], "confidence": "high|medium|low"}，不要解释。"""


def _post(messages: list[dict], model: str, timeout: float = 120) -> str:
    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0,
        'max_tokens': 1800,
    }
    headers = {'Authorization': f'Bearer {qwen_api._api_key()}', 'Content-Type': 'application/json'}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:300]}')
    return response.json()['choices'][0]['message']['content']


def parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    start = text.find('[')
    end = text.rfind(']')
    if start < 0 or end < start:
        raise ValueError(f'no JSON array: {text[:200]}')
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list):
        raise ValueError('not a list')
    return data


def classify_batch(blocks: list[dict], model: str) -> dict[str, dict]:
    lines = []
    for b in blocks:
        excerpt = re.sub(r'\s+', ' ', b['text'])[:6000]
        lines.append(json.dumps({'block_id': b['block_id'], 'source': b['source_title'], 'page': b['page'], 'excerpt': excerpt}, ensure_ascii=False))
    prompt = '逐条标注以下教材块：\n' + '\n'.join(lines)
    raw = _post([
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': prompt},
    ], model)
    parsed = parse_json_array(raw)
    result = {}
    for item in parsed:
        if item.get('block_id') in {b['block_id'] for b in blocks}:
            primary = item.get('primary')
            if primary not in TYPES:
                continue
            labels = [x for x in (item.get('labels') or [primary]) if x in TYPES]
            result[item['block_id']] = {
                'primary': primary,
                'labels': labels or [primary],
                'confidence': item.get('confidence', 'medium'),
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Qwen content_type classifier')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--reviewed-only', action='store_true')
    parser.add_argument('--model', default='qwen-plus')
    parser.add_argument('--batch', type=int, default=10)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    if not args.all and not args.reviewed_only:
        args.reviewed_only = True

    draft = json.loads(DRAFT.read_text(encoding='utf-8'))
    by = {b['block_id']: b for b in draft['blocks']}
    review = json.loads(REVIEW.read_text(encoding='utf-8'))
    reviewed_ids = [r['block_id'] for r in review['rows']]
    teacher = {r['block_id']: r['teacher_primary'] for r in review['rows']}
    blocks = [by[i] for i in reviewed_ids] if args.reviewed_only else list(draft['blocks'])
    if args.limit:
        blocks = blocks[:args.limit]

    results: dict[str, dict] = {}
    started = time.perf_counter()
    for start in range(0, len(blocks), args.batch):
        batch = blocks[start:start + args.batch]
        for attempt in range(3):
            try:
                results.update(classify_batch(batch, args.model))
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f'batch {start} failed: {exc}', file=sys.stderr)
                else:
                    time.sleep(2 + attempt * 3)
        print(f'  {min(start + args.batch, len(blocks))}/{len(blocks)}')
    elapsed = time.perf_counter() - started

    doc = {
        'version': 'content-type-llm/v0',
        'model': args.model,
        'scope': 'reviewed-120' if args.reviewed_only else 'all-1797',
        'count': len(blocks),
        'elapsed_seconds': round(elapsed, 1),
        'labels': results,
    }
    out = OUT_REVIEWED if args.reviewed_only else OUT_ALL
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    if args.reviewed_only:
        common = [i for i in reviewed_ids if i in results]
        agree = sum(1 for i in common if results[i]['primary'] == teacher[i])
        print(f'LLM accuracy vs teacher: {agree}/{len(common)} = {agree/len(common):.1%}')
        for i in reviewed_ids:
            if i in results and results[i]['primary'] != teacher[i]:
                print(f"  {i}: {results[i]['primary']} != {teacher[i]}")
    print('wrote', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

