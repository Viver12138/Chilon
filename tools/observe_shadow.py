"""Summarize shadow JSONL events collected from the retrieval gray path.

Usage:
    python tools/observe_shadow.py
    python tools/observe_shadow.py --path var/retrieval/shadow_events.jsonl --out-prefix var/retrieval/shadow_report
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / 'var/retrieval/shadow_events.jsonl'


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
    return round(values[idx], 1)


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize shadow router events')
    parser.add_argument('--path', type=Path, default=DEFAULT)
    parser.add_argument('--out-prefix', type=Path, default=None)
    args = parser.parse_args()
    if not args.path.exists():
        print(f'no shadow events at {args.path}')
        return 0
    events = []
    for line in args.path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        print('no valid events')
        return 0
    latencies = [float(e['elapsed_ms']) for e in events if e.get('elapsed_ms') is not None]
    empty = sum(1 for e in events if e.get('empty'))
    fallback = sum(1 for e in events if e.get('mode') == 'legacy_fallback')
    summary = {
        'events': len(events),
        'first_ts': events[0].get('ts'),
        'last_ts': events[-1].get('ts'),
        'router_flag': dict(Counter(e.get('router_flag') for e in events)),
        'mode': dict(Counter(e.get('mode') for e in events)),
        'auto_mode': dict(Counter(e.get('auto_mode') for e in events)),
        'intent': dict(Counter(e.get('plan_intent') for e in events)),
        'mode_mismatch_with_auto': sum(
            1 for e in events if e.get('auto_mode') and e.get('mode') != e.get('auto_mode')
        ),
        'empty': empty,
        'empty_rate': round(empty / len(events), 4),
        'legacy_fallback': fallback,
        'latency_ms': {
            'p50': pct(latencies, 0.50),
            'p95': pct(latencies, 0.95),
            'max': round(max(latencies), 1) if latencies else None,
            'mean': round(statistics.mean(latencies), 1) if latencies else None,
        },
        'top_queries': Counter(e.get('query') for e in events).most_common(10),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out_prefix:
        args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
        Path(str(args.out_prefix) + '.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        lines = ['# Shadow router report', '',
                 f"- events: {summary['events']}（{summary['first_ts']} → {summary['last_ts']}）",
                 f"- router_flag: {summary['router_flag']}",
                 f"- mode: {summary['mode']}；auto_mode: {summary['auto_mode']}",
                 f"- empty: {empty}/{summary['events']} = {summary['empty_rate']:.2%}",
                 f"- legacy_fallback: {fallback}",
                 f"- latency ms: {summary['latency_ms']}", '',
                 '## Top queries', '']
        for query, count in summary['top_queries']:
            lines.append(f'- {count}× {query}')
        Path(str(args.out_prefix) + '.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f'wrote {args.out_prefix}.json/.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
