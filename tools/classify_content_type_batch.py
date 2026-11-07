"""Offline, resumable content_type prelabeling with Qwen (qwen-plus).

Why: interactive long-text batches are slow and fragile. This script writes every
block immediately to a JSONL checkpoint, records API usage/cost, retries failed
batches, and can resume after a kill/network failure.

Usage:
    .\\.venv\\Scripts\\python.exe tools\\classify_content_type_batch.py --fresh
    .\\.venv\\Scripts\\python.exe tools\\classify_content_type_batch.py            # resume
    .\\.venv\\Scripts\\python.exe tools\\classify_content_type_batch.py --limit 200

Outputs:
    var/textbook_mapping/content_type_llm_checkpoint.jsonl
    var/textbook_mapping/content_type_llm_usage.json
    var/textbook_mapping/content_type_llm_all.json   (derived on completion)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'tools'))

import qwen_api  # noqa: E402
from classify_content_type_llm import SYSTEM, parse_json_array  # noqa: E402

DRAFT = ROOT / 'var/textbook_mapping/textbook_content_type_draft.json'
CHECKPOINT = ROOT / 'var/textbook_mapping/content_type_llm_checkpoint.jsonl'
USAGE = ROOT / 'var/textbook_mapping/content_type_llm_usage.json'
OUT = ROOT / 'var/textbook_mapping/content_type_llm_all.json'
URL = qwen_api.chat_base_url() + '/chat/completions'


def now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def load_done() -> dict[str, dict]:
    done = {}
    if not CHECKPOINT.exists():
        return done
    for line in CHECKPOINT.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get('block_id') and row.get('primary'):
            done[row['block_id']] = row
    return done


def append_rows(rows: list[dict]) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT.open('a', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        fh.flush()


def load_usage() -> dict:
    if USAGE.exists():
        return json.loads(USAGE.read_text(encoding='utf-8'))
    return {
        'model': None,
        'requests': 0,
        'failed_batches': 0,
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'seconds': 0.0,
        'prices_cny_per_million': {},
        'estimated_cost_cny': 0.0,
        'updated_at': None,
    }


def save_usage(usage: dict) -> None:
    p_in = usage.get('prices_cny_per_million', {}).get('input', 0.0)
    p_out = usage.get('prices_cny_per_million', {}).get('output', 0.0)
    usage['estimated_cost_cny'] = round(
        usage['prompt_tokens'] / 1_000_000 * p_in + usage['completion_tokens'] / 1_000_000 * p_out, 4
    )
    usage['updated_at'] = now()
    USAGE.write_text(json.dumps(usage, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def post_batch(blocks: list[dict], model: str, timeout: float) -> tuple[str, dict]:
    lines = []
    for b in blocks:
        excerpt = re.sub(r'\s+', ' ', b['text'])[:6000]
        lines.append(json.dumps(
            {'block_id': b['block_id'], 'source': b['source_title'], 'page': b['page'], 'excerpt': excerpt},
            ensure_ascii=False,
        ))
    prompt = '逐条标注以下教材块：\n' + '\n'.join(lines)
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'max_tokens': 2000,
    }
    headers = {'Authorization': f'Bearer {qwen_api._api_key()}', 'Content-Type': 'application/json'}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:300]}')
    body = response.json()
    return body['choices'][0]['message']['content'], body.get('usage') or {}


def main() -> int:
    parser = argparse.ArgumentParser(description='Resumable Qwen content_type batch prelabel')
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='process at most N pending blocks')
    parser.add_argument('--batch', type=int, default=20)
    parser.add_argument('--workers', type=int, default=1, help='parallel batch requests')
    parser.add_argument('--model', default=qwen_api.chat_model())
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--max-retries', type=int, default=3)
    parser.add_argument('--price-in', type=float, default=0.8, help='CNY per 1M prompt tokens')
    parser.add_argument('--price-out', type=float, default=2.0, help='CNY per 1M completion tokens')
    args = parser.parse_args()

    if args.fresh:
        CHECKPOINT.unlink(missing_ok=True)
        USAGE.unlink(missing_ok=True)
        OUT.unlink(missing_ok=True)

    draft = json.loads(DRAFT.read_text(encoding='utf-8'))
    all_blocks = draft['blocks']
    done = load_done()
    pending = [b for b in all_blocks if b['block_id'] not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f'total={len(all_blocks)} done={len(done)} pending={len(pending)} model={args.model}', flush=True)
    if not pending:
        return 0

    usage = load_usage()
    usage['model'] = args.model
    usage.setdefault('prices_cny_per_million', {})
    usage['prices_cny_per_million'] = {'input': args.price_in, 'output': args.price_out}
    started = time.perf_counter()
    failed = 0

    def run_batch(batch: list[dict]) -> tuple[list[dict], dict, str | None]:
        content = None
        batch_usage = {}
        last_error = None
        for attempt in range(1, args.max_retries + 1):
            try:
                t0 = time.perf_counter()
                content, batch_usage = post_batch(batch, args.model, args.timeout)
                batch_usage = dict(batch_usage)
                batch_usage['_seconds'] = round(time.perf_counter() - t0, 1)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(min(30, 2 ** attempt))
        if content is None:
            return [], batch_usage, f'request failed: {last_error}'
        try:
            parsed = parse_json_array(content)
        except Exception as exc:  # noqa: BLE001
            return [], batch_usage, f'parse failed: {exc}; raw={content[:200]}'
        by_id = {b['block_id']: b for b in batch}
        rows = []
        for item in parsed:
            block_id = item.get('block_id')
            if block_id not in by_id:
                continue
            primary = item.get('primary')
            if primary not in ('definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other'):
                continue
            labels = [x for x in (item.get('labels') or [primary]) if x in (
                'definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other')]
            rows.append({
                'block_id': block_id,
                'primary': primary,
                'labels': labels or [primary],
                'confidence': item.get('confidence', 'medium'),
                'model': args.model,
                'created_at': now(),
            })
        if not rows:
            return [], batch_usage, 'parse yielded 0 valid rows'
        return rows, batch_usage, None

    batches = [pending[i:i + args.batch] for i in range(0, len(pending), args.batch)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(run_batch, batch): batch for batch in batches}
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            rows, batch_usage, error = future.result()
            usage['requests'] += 1
            usage['prompt_tokens'] += int(batch_usage.get('prompt_tokens') or 0)
            usage['completion_tokens'] += int(batch_usage.get('completion_tokens') or 0)
            usage['total_tokens'] += int(batch_usage.get('total_tokens') or 0)
            usage['seconds'] = round(usage.get('seconds', 0.0) + float(batch_usage.get('_seconds') or 0), 1)
            if error:
                failed += 1
                usage['failed_batches'] += 1
                save_usage(usage)
                print(f'  batch failed: {error}', flush=True)
                continue
            append_rows(rows)
            done.update({r['block_id']: r for r in rows})
            completed += len(rows)
            save_usage(usage)
            print(f'  {completed}/{len(pending)} (+{len(rows)} saved, '
                  f'workers={args.workers}, cost≈¥{usage["estimated_cost_cny"]:.3f})', flush=True)

    # Derive combined output for downstream (only completed blocks).
    labels = {bid: {'primary': r['primary'], 'labels': r['labels'], 'confidence': r.get('confidence')}
              for bid, r in done.items()}
    OUT.write_text(json.dumps({
        'version': 'content-type-llm/v0',
        'model': args.model,
        'scope': 'all-1797' if len(done) == len(all_blocks) else 'partial',
        'count': len(done),
        'labels': labels,
        'usage': usage,
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'done={len(done)} failed_batches={failed} '
          f'usage={usage["prompt_tokens"]}+{usage["completion_tokens"]} tokens '
          f'cost≈¥{usage["estimated_cost_cny"]:.3f} elapsed={time.perf_counter()-started:.0f}s', flush=True)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
