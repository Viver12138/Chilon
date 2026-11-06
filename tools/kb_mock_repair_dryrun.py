#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟题 931 题本地修复 dry-run（task-24，只读 PG，不写 PG/vault、不调 OCR）。

做什么：
1. 按 67 套重建「题号 ↔ knowledge_questions」映射：
   - 从每个 chunk 文本解析可见题号边界，拆出各题段落（含 31 个多题块）；
   - 按套检测整体偏移（`首见题号 - question_no` 的众数）与漏题；
   - 用单调序列对齐（先最大化匹配数、再最大化题号吻合度）把段落分配给 931 个 qid；
   - 无法分配的 qid 标 unresolved（写进 ocr_needed.txt）。
2. 输出：
   - `var/mock_annotations/repaired_931.json`：931 条 {qid, text, resolved, mapping_confidence, ...}
   - `var/mock_annotations/repair_report.md`：resolved/unresolved、31 个多题块拆分、pilot 19 块修复、
     OCR 清单、映射置信度、校验结果与建议
   - `var/mock_annotations/ocr_needed.txt`：必须重 OCR/人工补的准确 qid 清单
3. 只读校验：qid 唯一、每套题号连续 1..N、resolved 文本非空、可见题号单调递增。

用法（.venv，含 psycopg）：
    .\\.venv\\Scripts\\python.exe tools/kb_mock_repair_dryrun.py
    ... --database-url <连接串>     # 默认 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL → 容器 env
退出码：0 成功；2 输入/校验失败；3 数据库不可用；4 缺依赖。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse

try:
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'var' / 'mock_annotations'
DEFAULT_OUT = OUT_DIR / 'repaired_931.json'
DEFAULT_REPORT = OUT_DIR / 'repair_report.md'
DEFAULT_OCR = OUT_DIR / 'ocr_needed.txt'
DEFAULT_PILOT = OUT_DIR / 'pilot_100.json'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
SEG_MIN = 40
PATTERNS = [
    re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
    re.compile(r'(?<=[\s。；;：:])(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
]


def die(msg, code=2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def _db_url(database_url: str | None = None):
    if database_url:
        return database_url, '--database-url'
    for env in ('CHILON_TEST_DATABASE_URL', 'CHILON_DATABASE_URL'):
        if os.environ.get(env):
            return os.environ[env], f'环境变量 {env}'
    try:
        p = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError('找不到 docker；请用 --database-url 或设置 CHILON_TEST_DATABASE_URL')
    pw = (p.stdout or '').strip()
    if p.returncode != 0 or not pw:
        raise RuntimeError('无法读取容器 env；请用 --database-url 或设置环境变量')
    return (f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}',
            f'容器 {CONTAINER} env（{DB_HOST}:{DB_PORT}/{DB_NAME}）')


def boundaries(text: str):
    t = text or ''
    found = {}
    for pat in PATTERNS:
        for m in pat.finditer(t):
            n = int(m.group(1))
            if 1 <= n <= 25 and m.start() not in found:
                found[m.start()] = n
    return sorted(found.items())


def segments(text: str):
    t = text or ''
    bs = boundaries(t)
    return [(n, t[pos:(bs[i + 1][0] if i + 1 < len(bs) else len(t))].strip())
            for i, (pos, n) in enumerate(bs)]


def best_offset(qnos, available):
    """返回 (匹配数, 偏移 d)：visible = question_no + d 命中最多的 d。"""
    best = (0, 0)
    for d in range(-12, 13):
        m = sum(1 for q in qnos if (q + d) in available)
        if m > best[0] or (m == best[0] and abs(d) < abs(best[1])):
            best = (m, d)
    return best


def align(recs, seglist, offset):
    """单调序列对齐：字典序最大化匹配数，再最大化题号吻合分。

    recs: [{question_no,...}] 升序；seglist: [(visible_no, text, chunk_key)] 按 visible 升序。
    返回 {record_index: segment_index}。
    """
    n, m = len(recs), len(seglist)
    dp = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        bt[i][0] = ('skipR',)
    for j in range(m + 1):
        bt[0][j] = ('skipS',)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            q = recs[i - 1]['question_no']
            v = seglist[j - 1][0]
            if v == q:
                w = 20
            elif offset is not None and v == q + offset:
                w = 12
            elif abs(v - q) <= 1:
                w = 6
            elif abs(v - q) <= 3:
                w = 2
            else:
                w = 1
            cand = [
                (dp[i - 1][j], ('skipR',)),
                (dp[i][j - 1], ('skipS',)),
                ((dp[i - 1][j - 1][0] + 1, dp[i - 1][j - 1][1] + w), ('match',)),
            ]
            dp[i][j], ch = max(cand, key=lambda x: x[0])
            bt[i][j] = ch
    matches, i, j = {}, n, m
    while i > 0 or j > 0:
        ch = bt[i][j]
        if ch[0] == 'match':
            matches[i - 1] = j - 1
            i -= 1
            j -= 1
        elif ch[0] == 'skipR':
            i -= 1
        else:
            j -= 1
    return matches


def fetch_chunks(url):
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id::text, s.title, q.question_no, c.chunk_key,
               (c.locator->>'page_number')::int, c.text_content
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        JOIN knowledge_questions q
          ON q.document_version_id = c.document_version_id AND q.stem_locator = c.locator
        WHERE s.source_type = 'mock_exam'
        ORDER BY s.title, q.question_no::int
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='模拟题 931 题本地修复 dry-run（只读）')
    ap.add_argument('--database-url', default=None,
                    help='PG 连接串；默认 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL → 容器 env')
    ap.add_argument('--pilot', default=str(DEFAULT_PILOT),
                    help='pilot_100.json（用于 19 个污染块修复结果）')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--report', default=str(DEFAULT_REPORT))
    ap.add_argument('--ocr-needed', default=str(DEFAULT_OCR))
    args = ap.parse_args(argv)

    if psycopg is None:
        die('缺少 psycopg：请用 .venv 运行', code=4)
    try:
        url, db_label = _db_url(args.database_url)
        rows = fetch_chunks(url)
    except Exception as e:  # noqa: BLE001
        die(f'数据库读取失败：{type(e).__name__}: {e}', code=3)
    if len(rows) != 931:
        die(f'mock chunk 数 {len(rows)}，预期 931')

    sets = collections.OrderedDict()
    for sid, title, qno, chunk_key, page, text in rows:
        sets.setdefault(sid, {'source_id': sid, 'set_title': title, 'records': []})
        sets[sid]['records'].append({
            'qid': f'mock_{sid}_q{int(qno):02d}', 'question_no': int(qno),
            'chunk_key': chunk_key, 'page': page, 'original_text': text or '',
        })

    items, unresolved, errors = [], [], []
    mapping_methods = collections.Counter()
    confidence = collections.Counter()
    set_stats = []
    multi_chunks = []  # 原 chunk 含 ≥2 个题号边界
    for sid, st in sets.items():
        recs = sorted(st['records'], key=lambda r: r['question_no'])
        qnos = [r['question_no'] for r in recs]
        # 拆段：每个 chunk 内按边界拆，段长 ≥40 才可用；同题号取最长
        pool, multi_count = [], 0
        for r in recs:
            segs = segments(r['original_text'])
            valid = [(n, s) for n, s in segs if len(s) >= SEG_MIN]
            if len(segs) > 1:
                multi_count += 1
                multi_chunks.append({'source_id': sid, 'set_title': st['set_title'],
                                     'qid': r['qid'], 'chunk_key': r['chunk_key'],
                                     'question_no': r['question_no'],
                                     'visible_numbers': [n for n, _s in segs],
                                     'segment_lengths': [len(s) for _n, s in segs]})
            for n, s in valid:
                pool.append((n, s, r['chunk_key'], r['qid']))
        uniq = {}
        for n, s, key, qid in pool:
            if n not in uniq or len(s) > len(uniq[n][0]):
                uniq[n] = (s, key, qid)
        seglist = [(n, uniq[n][0], uniq[n][1], uniq[n][2]) for n in sorted(uniq)]
        available = set(uniq)
        match_n, offset = best_offset(qnos, available)
        frac = match_n / len(qnos) if qnos else 0
        if offset == 0 and frac >= 0.8:
            method = 'number-aligned'
        elif frac >= 0.8:
            method = f'offset{offset:+d}'
        else:
            method = 'order-alignment'
        mapping_methods[method] += 1
        matched = align(recs, seglist, offset)
        assigned_visible = []
        for i, r in enumerate(recs):
            rec = {
                'qid': r['qid'], 'source_id': sid, 'set_title': st['set_title'],
                'question_no': r['question_no'], 'chunk_key': r['chunk_key'],
                'page': r['page'], 'original_chunk_len': len(r['original_text']),
                'mapping_method': method, 'set_offset': offset,
            }
            if i in matched:
                v, txt, key, src_qid = seglist[matched[i]]
                expected = r['question_no'] + offset
                if v == r['question_no'] or (frac >= 0.8 and v == expected):
                    conf = 'high'
                elif abs(v - expected) <= 1:
                    conf = 'medium'
                else:
                    conf = 'low'
                split_multi = any(m['source_id'] == sid and m['chunk_key'] == key
                                  for m in multi_chunks)
                if split_multi:
                    rtype = 'split_multi'
                elif method == 'order-alignment' or conf == 'low':
                    rtype = 'order_repaired'
                else:
                    rtype = 'single'
                rec.update({'resolved': True, 'text': txt, 'text_len': len(txt),
                            'assigned_visible_no': v, 'mapping_confidence': conf,
                            'split_from_chunk': key, 'split_from_multi': split_multi,
                            'repair_type': rtype, 'unresolved_reason': None})
                confidence[conf] += 1
                assigned_visible.append((r['question_no'], v))
            else:
                rec.update({'resolved': False, 'text': None, 'text_len': 0,
                            'assigned_visible_no': None, 'mapping_confidence': 'unresolved',
                            'split_from_chunk': None, 'split_from_multi': False,
                            'repair_type': 'unresolved',
                            'unresolved_reason': ('set_has_no_segment' if not seglist
                                                  else 'no_matching_segment')})
                unresolved.append(rec)
            items.append(rec)
        # 每套统计
        res_n = sum(1 for r in items if r['source_id'] == sid and r['resolved'])
        set_stats.append({'source_id': sid, 'title': st['set_title'], 'questions': len(recs),
                          'segments': len(seglist), 'offset': offset, 'method': method,
                          'resolved': res_n, 'unresolved': len(recs) - res_n,
                          'multi_chunks': multi_count})

    # ---- 多题块拆分结果
    for m in multi_chunks:
        used = [r for r in items if r['resolved'] and r['split_from_chunk'] == m['chunk_key']
                and r['source_id'] == m['source_id']]
        m['segments_used'] = len(used)
        m['fully_used'] = len(used) == len(m['segment_lengths'])

    orig_text_by_qid = {r['qid']: r['original_text'] for st in sets.values() for r in st['records']}
    # ---- pilot 19 污染块修复结果
    pilot_rows = []
    pilot_contaminated = []
    if pathlib.Path(args.pilot).exists():
        pilot = json.loads(pathlib.Path(args.pilot).read_text(encoding='utf-8'))
        pilot_contaminated = [x for x in pilot.get('items', [])
                              if any(k in (x.get('annotation', {}).get('rationale') or '')
                                     for k in ('块含', '残缺', 'OCR'))]
        by_qid = {r['qid']: r for r in items}
        for x in pilot_contaminated:
            qid = x['question_id']
            rec = by_qid.get(qid)
            if not rec:
                pilot_rows.append({'qid': qid, 'status': '不在 931 中'})
                continue
            # pilot 当时用的是该 chunk 的首段文本
            first = segments(orig_text_by_qid.get(qid, ''))
            orig_first = first[0][1] if first else rec['original_text']
            changed = bool(rec['resolved'] and rec['text'].strip()[:80] != orig_first.strip()[:80])
            pilot_rows.append({
                'qid': qid, 'set_title': rec.get('set_title'), 'question_no': rec['question_no'],
                'question_type': x.get('question_type'),
                'resolved': rec['resolved'], 'mapping_method': rec['mapping_method'],
                'mapping_confidence': rec['mapping_confidence'],
                'assigned_visible_no': rec.get('assigned_visible_no'),
                'original_visible': [n for n, _s in first],
                'text_changed_vs_pilot': changed,
                'text_len': rec.get('text_len'),
                'rationale': x.get('annotation', {}).get('rationale'),
            })

    # ---- 语义残缺（pilot 已知：无 primary 且 rationale 含“残缺”），并入 OCR 清单
    pilot_semantic = []
    if pathlib.Path(args.pilot).exists():
        pilot_by_qid = {x['question_id']: x for x in pilot.get('items', [])}
        for d in pilot_rows:
            x = pilot_by_qid.get(d['qid'])
            if not x:
                continue
            ann = x.get('annotation') or {}
            if not ann.get('kp_primary') and '残缺' in (ann.get('rationale') or ''):
                pilot_semantic.append(d)

    # ---- 校验
    qids = [r['qid'] for r in items]
    if len(qids) != 931:
        errors.append(f'qid 数 {len(qids)} ≠ 931')
    if len(set(qids)) != 931:
        errors.append('qid 不唯一')
    for sid, st in sets.items():
        nos = sorted(r['question_no'] for r in st['records'])
        if nos != list(range(1, len(nos) + 1)):
            errors.append(f'{st["set_title"]}: question_no 不连续 {nos[:5]}…')
    if any(r['resolved'] and not (r['text'] or '').strip() for r in items):
        errors.append('存在 resolved 但文本为空的条目')
    # 可见题号随题号单调（DP 保证，仍校验）
    for sid, st in sets.items():
        seq = [(r['question_no'], r['assigned_visible_no']) for r in items
               if r['source_id'] == sid and r['resolved']]
        if seq != sorted(seq):
            errors.append(f'{st["set_title"]}: 题号映射非单调')

    resolved_n = sum(1 for r in items if r['resolved'])
    unresolved_n = 931 - resolved_n
    high = confidence['high']
    medium = confidence['medium']
    low = confidence['low']

    # ---- 写 repaired_931.json
    payload = {
        'schema': 'chilon-mock-repair/v1',
        'source': 'PostgreSQL knowledge_chunks（mock_exam 931）',
        'db': db_label,
        'read_only': True,
        'summary': {
            'total': 931, 'resolved': resolved_n, 'unresolved': unresolved_n,
            'resolved_pct': round(resolved_n / 931 * 100, 2),
            'confidence': dict(confidence),
            'mapping_methods': dict(mapping_methods),
            'multi_chunks': len(multi_chunks),
            'pilot_contaminated': len(pilot_rows),
            'pilot_semantic_truncated': len(pilot_semantic),
            'validation_errors': errors,
        },
        'items': items,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')

    # ---- ocr_needed.txt
    ocr_lines = ['# 模拟题本地修复 dry-run：必须重 OCR / 人工补的 qid 清单（按套分组）',
                 '# 格式：套标题行以 # 开头；明细行 qid|reason|set_title|question_no',
                 f'# 生成：tools/kb_mock_repair_dryrun.py（只读；未写 PG/vault、未调 OCR）',
                 f'# 统计：unresolved {unresolved_n}/931; 语义残缺 {len(pilot_semantic)}；合计 {unresolved_n + len(pilot_semantic)}']
    sem_by_qid = {d['qid']: d for d in pilot_semantic}
    # 按套分组：套内 unresolved（按题号）→ 语义残缺
    for sid, st in sets.items():
        rows = [r for r in items if r['source_id'] == sid and not r['resolved']]
        rows += [r for r in items if r['source_id'] == sid and r['qid'] in sem_by_qid]
        if not rows:
            continue
        rows.sort(key=lambda r: r['question_no'])
        ocr_lines.append('')
        ocr_lines.append(f"# 套：{st['set_title']}（{len(rows)} 题）")
        for r in rows:
            reason = ('pilot_semantic_truncated' if r['qid'] in sem_by_qid
                      else r['unresolved_reason'])
            ocr_lines.append(f"{r['qid']}|{reason}|{st['set_title']}|{r['question_no']}")
    ocr_path = pathlib.Path(args.ocr_needed)
    ocr_path.write_text('\n'.join(ocr_lines) + '\n', encoding='utf-8')

    # ---- 报告
    L = ['---', 'type: report', 'title: 模拟题 931 题本地修复 dry-run 报告', 'updated: 2026-11-06',
         'status: dry-run/read-only', '---', '',
         '# 模拟题 931 题本地修复 dry-run 报告', '',
         f'> 数据：PG `knowledge_chunks`（mock_exam 931）｜DB：{db_label}（只读查询）。  ',
         '> **未写 PG、未改 vault、未调 OCR**；产物仅 `var/mock_annotations/`。', '',
         '## 1. 总览', '',
         '| 指标 | 值 |', '| --- | --- |',
         f'| 总题数 | 931 |',
         f'| **resolved** | **{resolved_n}（{resolved_n/931*100:.1f}%）** |',
         f'| **unresolved** | **{unresolved_n}（{unresolved_n/931*100:.1f}%）** |',
         f'| 映射置信 high / medium / low | {high} / {medium} / {low} |',
         f'| 多题块（原 chunk 含 ≥2 题号） | {len(multi_chunks)} |',
         f'| pilot 19 污染块（已纳入修复） | {len(pilot_rows)} |',
         f'| pilot 语义残缺（边界无法修） | {len(pilot_semantic)} |',
         f'| 校验错误 | **{len(errors)}** |', '']
    if errors:
        L += ['**校验错误**：', ''] + [f'- {e}' for e in errors] + ['']
    L += ['## 2. 映射方法（67 套）', '', '| 方法 | 套数 | 说明 |', '| --- | --- | --- |']
    for m, c in mapping_methods.most_common():
        desc = {'number-aligned': '首见题号与 question_no 基本一致（偏移 0）',
                'order-alignment': '题号整体/局部错位，按套内顺序单调对齐',
                }.get(m, '整体偏移 offset，按 question_no+offset 对齐')
        L.append(f'| {m} | {c} | {desc} |')
    oa = [s for s in set_stats if s['method'] == 'order-alignment']
    if oa:
        L += ['', f'**{len(oa)} 套为顺序对齐（题号整体/局部错位，需人工核对映射）**：', '',
              '| 套 | 题数 | resolved | unresolved | 偏移 |', '| --- | --- | --- | --- | --- |']
        for s2 in oa:
            L.append(f'| {s2["title"]} | {s2["questions"]} | {s2["resolved"]} | '
                     f'{s2["unresolved"]} | {s2["offset"]:+d} |')
        L += ['']
    L += ['', '### 2.1 按套概况（67 套逐套）', '',
          '| 套 | 题数 | 可用段 | 偏移 | 方法 | resolved | unresolved |', '| --- | --- | --- | --- | --- | --- | --- |']
    for s in sorted(set_stats, key=lambda x: x['title']):
        L.append(f'| {s["title"]} | {s["questions"]} | {s["segments"]} | {s["offset"]:+d} | '
                 f'{s["method"]} | {s["resolved"]} | {s["unresolved"]} |')
    # Top 20 修复示例：优先 split_multi / order_repaired，展示原块首段 → 修复文本
    cand = [r for r in items if r['resolved'] and r['repair_type'] in ('split_multi', 'order_repaired')]
    cand = cand[:20]
    L += ['', '### 2.2 Top 20 修复示例（原 chunk 首段 → 修复后文本）', '']
    for i, r in enumerate(cand, 1):
        orig = segments(orig_text_by_qid.get(r['qid'], ''))
        orig_first = orig[0][1] if orig else orig_text_by_qid.get(r['qid'], '')
        L += [f'### 示例 {i}：`{r["qid"]}`（{r["set_title"][:26]}，q{r["question_no"]}，'
              f'{r["repair_type"]} / {r["mapping_confidence"]}）', '',
              f'- 原 chunk 首段（{len(orig_first)} 字）：{orig_first[:100].replace(chr(10), " ")}…',
              f'- 修复文本（{r["text_len"]} 字）：{r["text"][:100].replace(chr(10), " ")}…', '']
    L += ['', f'## 3. {len(multi_chunks)} 个多题块的拆分结果', '',
          f'- 原 chunk 含 ≥2 个题号边界的块：**{len(multi_chunks)}** 个'
          '（probe 中 31 个「可拆」+ 2 个「缺文本」= 33）',
          f'- 其中各段都被分配给 qid（fully_used）：**{sum(1 for m in multi_chunks if m["fully_used"])}** 个',
          f'- 部分/未使用：{sum(1 for m in multi_chunks if not m["fully_used"])} 个（通常是额外段属于本题集外的题）', '',
          '| chunk_key | 套（截断） | 原 question_no | 可见题号 | 段长 | 已用段数 |',
          '| --- | --- | --- | --- | --- | --- |']
    for m in multi_chunks[:40]:
        L.append(f'| `{m["chunk_key"]}` | {m["set_title"][:16]} | {m["question_no"]} | '
                 f'{" / ".join(str(n) for n in m["visible_numbers"])} | '
                 f'{" / ".join(str(x) for x in m["segment_lengths"])} | {m["segments_used"]} |')
    if len(multi_chunks) > 40:
        L.append(f'| … | 共 {len(multi_chunks)} 个 | | | |')
    L += ['', '## 4. pilot 100 的 19 个污染块修复结果', '',
          '| # | qid | question_no | resolved | 置信 | 修复后题号 | 文本是否变化 | 说明 |',
          '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for i, d in enumerate(pilot_rows, 1):
        if 'resolved' not in d:
            L.append(f'| {i} | `{d["qid"]}` | — | {d["status"]} | — | — | — | — |')
            continue
        L.append(f'| {i} | `{d["qid"]}` | {d["question_no"]} | {"✅" if d["resolved"] else "❌"} | '
                 f'{d["mapping_confidence"]} | {d["assigned_visible_no"]} | '
                 f'{"是（pilot 文本已换）" if d["text_changed_vs_pilot"] else "否"} | '
                 f'{d["rationale"] or ""} |')
    L += ['', f'- 19 块中 resolved：**{sum(1 for d in pilot_rows if d.get("resolved"))}**；'
          f'其中修复后 qid 对应文本与 pilot 标注文本不同：'
          f'**{sum(1 for d in pilot_rows if d.get("text_changed_vs_pilot"))}** 块'
          '（这些 qid 的 pilot 标注需按修复后文本复核/重标）。', '',
          '## 5. 必须重 OCR / 人工补的清单', '',
          f'- unresolved：**{unresolved_n}** 题（{unresolved_n/931*100:.1f}%）：'
          f'其中「整套无可用段」{sum(1 for r in items if r["unresolved_reason"]=="set_has_no_segment")} 题、'
          f'「套内有段但本题无匹配段」{sum(1 for r in items if r["unresolved_reason"]=="no_matching_segment")} 题。',
          f'- pilot 已确认语义残缺（题干截断/粘连，边界解析无法修）：**{len(pilot_semantic)}** 题：'
          + '、'.join(f'`{d["qid"]}`' for d in pilot_semantic),
          f'- **合计必须重 OCR/人工补：{unresolved_n + len(pilot_semantic)} 题'
          f'（{(unresolved_n + len(pilot_semantic))/931*100:.1f}%）**；准确 qid 见 `{pathlib.Path(args.ocr_needed).name}`（已按套分组）。', '',
          '### 5.1 unresolved 清单与原因', '',
          '| qid | 原因 | 套 | 题号 |', '| --- | --- | --- | --- |']
    for r in items:
        if not r['resolved']:
            L.append(f'| `{r["qid"]}` | {r["unresolved_reason"]} | {r["set_title"]} | {r["question_no"]} |')
    L += ['',
          '## 6. 校验', '',
          f'- qid 唯一：{"✅" if len(set(qids)) == 931 else "❌"}（931）',
          f'- 每套 question_no 连续 1..N：{"✅" if not any("不连续" in e for e in errors) else "❌"}',
          f'- resolved 文本非空：{"✅" if not any("文本为空" in e for e in errors) else "❌"}',
          f'- 可见题号随 question_no 单调：{"✅" if not any("非单调" in e for e in errors) else "❌"}', '',
          '## 7. 结论与建议', '',
          f'- **本地可应用（resolved）：{resolved_n}/931 = {resolved_n/931*100:.1f}%**；'
          f'其中 high {high}、medium {medium}、low（顺序对齐、需抽样核对）{low}。',
          f'- **必须重 OCR/人工补：{unresolved_n + len(pilot_semantic)}/931 = '
          f'{(unresolved_n + len(pilot_semantic))/931*100:.1f}%**（unresolved {unresolved_n} + pilot 语义残缺 {len(pilot_semantic)}）。',
          '- 建议：**「本地应用 + 少量 OCR」可行**：',
          f'  1. 先落地 resolved 的 {resolved_n} 条修复文本，并对 low 置信的 {low} 条做人工抽样核对'
          '（重点检查“顺序对齐”的 26 套：题号可能整段错位 1–2 题）；',
          '  2. 只对 ocr_needed.txt 中 ' + str(unresolved_n + len(pilot_semantic)) + ' 题重 OCR/人工补，'
          '不需要全库重跑；',
          '  3. 修复后仍需保留 `chunk_key/locator` 溯源；pilot 19 块中文本变化的 qid 必须按新文本复核标注；',
          '  4. 本轮为 dry-run：未 UPDATE/INSERT PG、未写 vault、未调 OCR；确认后再做 apply 方案。', '',
          '---', '',
          f'> 生成：`tools/kb_mock_repair_dryrun.py`；明细：`{pathlib.Path(args.out).name}`；'
          f'OCR 清单：`{pathlib.Path(args.ocr_needed).name}`。', '']
    pathlib.Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.report).write_text('\n'.join(L), encoding='utf-8')

    print('=' * 72)
    print('模拟题 931 题本地修复 dry-run（只读）')
    print('=' * 72)
    print(f'resolved {resolved_n}/931 = {resolved_n/931*100:.1f}%｜unresolved {unresolved_n}｜'
          f'语义残缺 {len(pilot_semantic)}｜需 OCR 合计 {unresolved_n + len(pilot_semantic)}')
    print(f'置信 high/medium/low = {high}/{medium}/{low}｜映射方法 {dict(mapping_methods)}')
    print(f'多题块 {len(multi_chunks)}｜pilot 19 块 resolved '
          f'{sum(1 for d in pilot_rows if d.get("resolved"))}｜文本变化 '
          f'{sum(1 for d in pilot_rows if d.get("text_changed_vs_pilot"))}')
    print(f'校验错误 {len(errors)}')
    print(f'产物：{args.out}')
    print(f'      {args.report}')
    print(f'      {args.ocr_needed}')
    return 0 if not errors else 2


if __name__ == '__main__':
    sys.exit(main())
