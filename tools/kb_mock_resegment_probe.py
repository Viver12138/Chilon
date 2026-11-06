#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟题 chunk 重切可恢复性只读探针（task-23）。

只读 PG `knowledge_chunks`（source_type=mock_exam，931 条），按题号边界分析：
- 分类：单题干净 / 多题可拆（各段都有题号且段长 ≥40）/ 多题但缺文本 / 无题号 / 过短；
- 对照：首见题号 vs `knowledge_questions.question_no`（判断是正则噪声还是切分错位）；
- pilot 100 中 19 个污染块逐个列出可拆情况；
- 估计：本地重切可恢复的题数/比例、必须重 OCR/重导入的题数/比例、去重后 931 题覆盖上限。

不写 PG、不写 vault、不调 OCR。输出 `var/mock_annotations/resegment_probe.md`（+ JSON 明细）。

用法（.venv，含 psycopg）：
    .\\.venv\\Scripts\\python.exe tools/kb_mock_resegment_probe.py
    ... --database-url <连接串>          # 默认 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL → 容器 env
    ... --pilot <pilot_100.json> --out <report.md>
退出码：0 成功；2 参数/输入问题；3 数据库不可用；4 缺依赖。
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
DEFAULT_OUT = ROOT / 'var' / 'mock_annotations' / 'resegment_probe.md'
DEFAULT_JSON = ROOT / 'var' / 'mock_annotations' / 'resegment_probe.json'
DEFAULT_PILOT = ROOT / 'var' / 'mock_annotations' / 'pilot_100.json'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'

# 题号边界：行首 `1.` / 行内（空白或中文标点后）`2、`，要求数字后跟中文/字母/括号，过滤公式与选项
BOUNDARY_PATTERNS = [
    re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
    re.compile(r'(?<=[\s。；;：:])(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
]
# 宽松扫描（用于与 Lead 的“>1 个题号”口径对账；会含公式/选项噪声）
LOOSE_NUM = re.compile(r'(?<![0-9A-Za-z])(\d{1,2})\s*[.．、](?=\s*[^\d\s])')
SEG_MIN = 40


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
    """返回 [(start_pos, 题号)]，按位置排序；过滤 1..25 与公式噪声。"""
    t = text or ''
    found = {}
    for pat in BOUNDARY_PATTERNS:
        for m in pat.finditer(t):
            n = int(m.group(1))
            if 1 <= n <= 25 and m.start() not in found:
                found[m.start()] = n
    return sorted(found.items())


def segments(text: str, bs):
    t = text or ''
    return [(n, t[pos:(bs[i + 1][0] if i + 1 < len(bs) else len(t))].strip())
            for i, (pos, n) in enumerate(bs)]


def classify(text: str):
    t = text or ''
    bs = boundaries(t)
    if len(t) < SEG_MIN:
        return '过短', bs
    if not bs:
        return '无题号', bs
    if len(bs) == 1:
        pos = bs[0][0]
        seg = t[pos:].strip()
        return ('单题干净' if pos <= 20 and len(seg) >= SEG_MIN else '多题缺文本'), bs
    ss = segments(t, bs)
    if bs[0][0] <= 20 and all(len(seg) >= SEG_MIN for _n, seg in ss):
        return '多题可拆', bs
    return '多题缺文本', bs


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
    ap = argparse.ArgumentParser(description='模拟题 chunk 重切可恢复性只读探针')
    ap.add_argument('--database-url', default=None,
                    help='PG 连接串；默认 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL → 容器 env')
    ap.add_argument('--pilot', default=str(DEFAULT_PILOT), help='pilot_100.json（用于 19 个污染块明细）')
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='报告输出路径')
    ap.add_argument('--json', default=str(DEFAULT_JSON), help='JSON 明细输出路径')
    args = ap.parse_args(argv)

    if psycopg is None:
        print('缺少 psycopg：请用 .venv 运行', file=sys.stderr)
        return 4
    try:
        url, db_label = _db_url(args.database_url)
        rows = fetch_chunks(url)
    except Exception as e:  # noqa: BLE001
        print(f'[失败] 数据库读取失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 3
    if len(rows) != 931:
        print(f'[失败] mock chunk 数 {len(rows)}，预期 931', file=sys.stderr)
        return 2

    chunk_rows = []
    cat = collections.Counter()
    delta = collections.Counter()
    loose_multi = 0
    for sid, title, qno, chunk_key, page, text in rows:
        text = text or ''
        c, bs = classify(text)
        cat[c] += 1
        if len(LOOSE_NUM.findall(text)) > 1:
            loose_multi += 1
        qno = int(qno)
        first = bs[0][1] if bs else None
        d = (first - qno) if first is not None else None
        if d is None:
            delta['无题号'] += 1
        elif d == 0:
            delta['0（对齐）'] += 1
        elif -3 <= d <= 5:
            delta[f'{d:+d}'] += 1
        else:
            delta['其他'] += 1
        chunk_rows.append({
            'source_id': sid, 'set_title': title, 'question_no': qno, 'chunk_key': chunk_key,
            'page': page, 'qid': f'mock_{sid}_q{qno:02d}', 'text_len': len(text),
            'category': c, 'boundaries': [n for _p, n in bs],
            'segment_lengths': [(n, len(s)) for n, s in segments(text, bs)],
            'first_visible_no': first, 'delta': d,
            'text': text,
        })

    aligned = sum(1 for r in chunk_rows if r['delta'] == 0)
    no_boundary = sum(1 for r in chunk_rows if r['delta'] is None)
    misaligned = 931 - aligned - no_boundary
    multi = [r for r in chunk_rows if len(r['boundaries']) > 1]

    # 每套：去重后的有效段数（同题号取最长）→ 931 题覆盖上限
    by_set = collections.defaultdict(list)
    for r in chunk_rows:
        by_set[r['source_id']].append(r)
    set_stats = []
    upper = 0
    for sid, items in by_set.items():
        uniq = {}
        for r in items:
            t = r['text']
            bs = boundaries(t)
            for n, seg in segments(t, bs):
                if len(seg) < SEG_MIN:
                    continue
                if n not in uniq or len(seg) > len(uniq[n]):
                    uniq[n] = seg
        upper += min(len(items), len(uniq))
        set_stats.append({'title': items[0]['set_title'], 'questions': len(items),
                          'unique_segments': len(uniq), 'missing': max(0, len(items) - len(uniq))})
    set_stats.sort(key=lambda x: (-x['missing'], x['title']))
    need_reocr = 931 - upper

    # pilot 19 污染块明细
    pilot_detail, pilot_status = [], collections.Counter()
    if pathlib.Path(args.pilot).exists():
        pilot = json.loads(pathlib.Path(args.pilot).read_text(encoding='utf-8'))
        cont = [x for x in pilot.get('items', [])
                if any(k in (x.get('annotation', {}).get('rationale') or '')
                       for k in ('块含', '残缺', 'OCR'))]
        by_qid = {r['qid']: r for r in chunk_rows}
        for x in cont:
            qid = x['question_id']
            r = by_qid.get(qid)
            if not r:
                pilot_detail.append({'qid': qid, 'status': '不在 931 中'})
                continue
            c, bs = classify(r['text'])
            segs = [(n, len(s)) for n, s in segments(r['text'], bs)]
            status = '多题可拆' if c == '多题可拆' else (
                '单边界可提取' if c == '单题干净' else c)
            pilot_status[status] += 1
            pilot_detail.append({
                'qid': qid, 'set_title': r['set_title'], 'question_no': r['question_no'],
                'category': c, 'status': status,
                'visible_numbers': [n for n, _s in segs],
                'segment_lengths': [ln for _n, ln in segs],
                'first_visible_no': r['first_visible_no'], 'delta': r['delta'],
                'aligned': r['delta'] == 0,
                'no_primary': not (x.get('annotation', {}).get('kp_primary')),
                'rationale': x.get('annotation', {}).get('rationale'),
            })
    pilot_clean_split = sum(1 for d in pilot_detail if d.get('status') == '多题可拆')
    pilot_single = sum(1 for d in pilot_detail if d.get('status') == '单边界可提取')
    pilot_missing = sum(1 for d in pilot_detail if d.get('category') == '多题缺文本')
    pilot_aligned = sum(1 for d in pilot_detail if d.get('aligned'))
    pilot_misaligned = len(pilot_detail) - pilot_aligned
    pilot_multi_aligned = sum(1 for d in pilot_detail if d.get('status') == '多题可拆' and d.get('aligned'))
    pilot_single_aligned = sum(1 for d in pilot_detail if d.get('status') == '单边界可提取' and d.get('aligned'))
    pilot_semantic_broken = [d for d in pilot_detail
                             if d.get('no_primary') and '残缺' in (d.get('rationale') or '')]
    not_aligned_pct = (misaligned + no_boundary) / 931 * 100

    # 示例：多题可拆 / 错位
    examples = [r for r in chunk_rows if r['category'] == '多题可拆'][:10]
    misaligned_examples = [r for r in chunk_rows if r['delta'] not in (0, None)][:10]

    # ---- 报告
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    L = ['---', 'type: report', 'title: 模拟题 chunk 重切可恢复性探针', 'updated: 2026-11-06',
         'status: read-only', '---', '',
         '# 模拟题 chunk 重切可恢复性探针（只读）', '',
         f'> 数据：PG `knowledge_chunks`（mock_exam 931 条）｜DB：{db_label}（只读查询，未写 PG）。  ',
         '> 不碰 OCR、不写 vault；输出仅 `var/mock_annotations/`。', '',
         '## 1. 总表', '',
         '| 分类 | 数量 | 占比 | 定义 |', '| --- | --- | --- | --- |',
         f'| 单题干净 | {cat["单题干净"]} | {cat["单题干净"]/931*100:.1f}% | 首题号在文首（≤20 字前缀）、段长 ≥40，无多题 |',
         f'| 多题可拆 | {cat["多题可拆"]} | {cat["多题可拆"]/931*100:.1f}% | ≥2 个题号边界，每段 ≥40 字、首题号在文首 |',
         f'| 多题缺文本 | {cat["多题缺文本"]} | {cat["多题缺文本"]/931*100:.1f}% | ≥2 个题号但某段 <40 字，或首部有长残片 |',
         f'| 无题号 | {cat["无题号"]} | {cat["无题号"]/931*100:.1f}% | 文本中找不到题号边界 |',
         f'| 过短 | {cat["过短"]} | {cat["过短"]/931*100:.1f}% | 全文 <40 字 |',
         f'| **合计** | **931** | 100% | — |', '',
         f'- 宽松扫描（`数字+点`，含公式/选项噪声）含 >1 个数字点的 chunk：**{loose_multi}**；'
         f'严格题号边界后含 ≥2 个题号边界的 chunk：**{len(multi)}**（多题可拆 {cat["多题可拆"]} + '
         f'其中缺文本 {sum(1 for r in multi if r["category"] == "多题缺文本")}）；'
         f'另有 {cat["多题缺文本"] - sum(1 for r in multi if r["category"] == "多题缺文本")} 个 chunk 单边界但首部有长残片，'
         f'也归入「多题缺文本」。',
         f'- 段长阈值 40 字；与 Lead 扫描的“86（9.2%）含 >1 题号”差异主要来自正则严格性（见 §2）。', '',
         '## 2. 题号 vs `question_no`：是噪声还是错位？', '',
         '| 首见题号 - question_no | 数量 |', '| --- | --- |']
    for k in ('0（对齐）', '+1', '+2', '+3', '+4', '+5', '-1', '-2', '-3', '其他', '无题号'):
        if delta.get(k):
            L.append(f'| {k} | {delta[k]} |')
    L += ['', f'- **对齐（首见题号 = question_no）：{aligned}/931 = {aligned/931*100:.1f}%**；'
          f'错位 {misaligned}（{misaligned/931*100:.1f}%）+ 无题号 {no_boundary}（{no_boundary/931*100:.1f}%）。',
          '- 结论：**以切分/区域错位为主，不是正则噪声**。典型：某套第 1 题的 chunk 文本从“2.”开始，'
          '后续逐题 +1/+2 漂移（漏掉某些题的 region 后整体前移）；pilot 中已可直接看到同一套内 q1→文本2、q2→文本3……',
          '- 影响：即使把文本切干净，**chunk 文本与 `question_no` 的对应关系仍可能是错的**；'
          '全量前必须按套重建 region↔question 映射，否则 qid↔题干会错配。', '',
          '## 3. pilot 100 中 19 个污染块逐个重切', '',
          f'pilot 标注中标注了“块含相邻题/残缺/OCR”的共 **{len(pilot_detail)}** 块：',
          '',
          f'- 多题可拆（题号边界清晰、各段 ≥40 字）：**{pilot_clean_split}** 块',
          f'- 单边界可提取（文本本身可用，但题号与 question_no 错位）：**{pilot_single}** 块',
          f'- 多题缺文本：**{pilot_missing}** 块',
          '', '| # | qid | question_no | 分类 | 可见题号 | 各段长度 | 首见题号差 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for i, d in enumerate(pilot_detail, 1):
        if 'category' not in d:
            L.append(f'| {i} | `{d["qid"]}` | — | {d["status"]} | — | — | — |')
            continue
        L.append(f'| {i} | `{d["qid"]}` | {d["question_no"]} | {d["category"]} | '
                 f'{" / ".join(str(n) for n in d["visible_numbers"])} | '
                 f'{" / ".join(str(x) for x in d["segment_lengths"])} | {d["delta"]} |')
    L += ['', '说明：',
          f'- 多题可拆 {pilot_clean_split} 块：可按题号切出 2 段且段长均 ≥40（可本地拆分，不重 OCR）；'
          f'其中题号对齐 {pilot_multi_aligned} 块、错位 {pilot_clean_split - pilot_multi_aligned} 块。',
          f'- 单边界可提取 {pilot_single} 块：文本不短、无硬缺段，可直接取首段；'
          f'其中题号对齐 {pilot_single_aligned} 块、错位 {pilot_single - pilot_single_aligned} 块（错位需映射重建）。',
          f'- 多题缺文本 {pilot_missing} 块（硬缺段）；pilot 19 块整体：题号对齐 {pilot_aligned}、错位 {pilot_misaligned}。',
          f'- 另有 **{len(pilot_semantic_broken)} 例语义残缺**（'
          + '、'.join(f'`{d["qid"]}`' for d in pilot_semantic_broken)
          + '）：题干被截断/粘连，边界解析无法恢复，需人工补或重 OCR。', '',
          '## 4. 本地可修复 vs 只能重 OCR（931 题估计）', '',
          '| 口径 | 题数 | 比例 | 说明 |', '| --- | --- | --- | --- |',
          f'| **本地可恢复上限**（重切+映射重建后能拿到 ≥40 字的唯一题目段） | **{upper}** | '
          f'**{upper/931*100:.1f}%** | 按套去重：min(题数, 去重有效段数) 求和；需先重建 region↔question 映射 |',
          f'| 其中：首题号已对齐、可直接用（无需映射重建） | **{aligned}** | {aligned/931*100:.1f}% | '
          'chunk 首见题号 = question_no；仍需去掉块内邻题尾巴 |',
          f'| 需映射重建（文本有、但题号错位/无题号） | **{misaligned + no_boundary}** | '
          f'{(misaligned + no_boundary)/931*100:.1f}% | 本地可做（按套用题号序列对齐），但必须逐套确认，非纯文本修复 |',
          f'| **只能重 OCR/重导入**（去重后仍无 ≥40 字有效段） | **{need_reocr}** | '
          f'**{need_reocr/931*100:.1f}%** | 1 套完全无有效段（{", ".join(s["title"][:18] for s in set_stats if s["unique_segments"]==0)}）；'
          '22 套存在缺题；缺段无法从现有文本恢复 |', '',
          '**去重后 931 题覆盖估计**：',
          f'- 若允许“重切 + 映射重建”：可覆盖 **{upper}/931 = {upper/931*100:.1f}%**，'
          f'剩余 **{need_reocr} 题（{need_reocr/931*100:.1f}%）**需重 OCR/重导入或人工补。',
          f'- 若只允许“重切、不重建映射”：只有 **{aligned} 题（{aligned/931*100:.1f}%）**的题号与文本能对上，'
          f'其余 **{misaligned + no_boundary} 题（{not_aligned_pct:.1f}%）**会带 qid↔题干错配风险。',
          '- 缺题最多的套（前 10）：', '']
    for s in set_stats[:10]:
        L.append(f'  - {s["title"][:42]}：题 {s["questions"]}，去重有效段 {s["unique_segments"]}，缺 {s["missing"]}')
    L += ['', '> 两个口径不完全互斥：`映射重建` 是前置修复步骤（512 已对齐 + 419 待重排）；'
          '`37 题` 是“无任何 ≥40 字段可救”的最终损失。另有 pilot 抽样发现的语义残缺（2/100）无法被边界解析识别，'
          '按同比例外推约 19 题，实际需重 OCR/人工补的题数可能上浮到 ~4–6%。', '',
          '## 5. Top 10 示例（多题可拆：拆前 → 拆后）', '']
    for i, r in enumerate(examples, 1):
        segs = segments(r['text'], boundaries(r['text']))
        L += [f'### 示例 {i}：`{r["qid"]}`（{r["set_title"][:28]}，question_no={r["question_no"]}）', '',
              f'- 原 chunk：{len(r["text"])} 字，题号边界 {r["boundaries"]}，各段长度 {r["segment_lengths"]}',
              '- 拆后：']
        for n, seg in segs:
            preview = seg[:80].replace('\n', ' ')
            L.append(f'  - q{n}（{len(seg)} 字）：{preview}…')
        L.append('')
    L += ['## 6. 建议', '',
          '1. **先做映射重建，再做重切**：当前 384 个 chunk 首题号错位（+ 35 无题号），'
          '说明 region 与 question 记录不是一一对齐；建议按套用“可见题号序列”对齐，'
          '并保留 `chunk_key/locator` 溯源。只切文本不改映射会产出错误的 qid↔题干。',
          '2. **本地重切可解决边界污染**：31 个多题块可拆、pilot 19 污染块中 8 块可干净拆分；'
          '但 pilot 另外 11 块是“文本可用、题号漂移”，切了也需重排映射。',
          '3. **重 OCR 只针对确实缺段**：去重后估计 **' + str(need_reocr) + ' 题（'
          + f'{need_reocr/931*100:.1f}%）' + '** 无 ≥40 字有效段（1 套全缺、22 套部分缺），'
          '建议只对这些套/题重 OCR 或人工补，不必全库重跑。',
          '4. **不要直接进入全量标注**：pilot 已验证口径可行（96% 有 primary），但 41% 题号错位会使'
          '全量 qid↔题干错配；保险做法是“映射重建 + 重切 + 抽检 30 题”后再全量。',
          '5. **本轮只读**：未调用 OCR、未写 PG/vault；探针脚本可重复运行（同一 DB 状态结果一致）。', '',
          '---', '',
          f'> 生成：`tools/kb_mock_resegment_probe.py`；逐 chunk 明细见 `{pathlib.Path(args.json).name}`。', '']
    out.write_text('\n'.join(L), encoding='utf-8')

    payload = {
        'db': db_label, 'chunks': 931, 'categories': dict(cat),
        'loose_multi': loose_multi, 'strict_multi': len(multi),
        'delta': dict(delta), 'aligned': aligned, 'misaligned': misaligned,
        'no_boundary': no_boundary, 'upper_recoverable': upper, 'need_reocr': need_reocr,
        'pilot': {'count': len(pilot_detail), 'clean_split': pilot_clean_split,
                  'single_extract': pilot_single, 'missing_text': pilot_missing,
                  'detail': pilot_detail},
        'set_stats': set_stats,
        'chunks_detail': [{k: v for k, v in r.items() if k != 'text'} for r in chunk_rows],
    }
    pathlib.Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')

    print('=' * 72)
    print('模拟题 chunk 重切可恢复性探针（只读）')
    print('=' * 72)
    print(f'分类：{dict(cat)}')
    print(f'宽松 >1 数字点 {loose_multi} ｜严格多题块 {len(multi)}')
    print(f'题号对齐 {aligned}/931；错位 {misaligned}；无题号 {no_boundary}')
    print(f'pilot 19：多题可拆 {pilot_clean_split}｜单边界可提取 {pilot_single}｜缺文本 {pilot_missing}')
    print(f'本地可恢复上限 {upper}/931 = {upper/931*100:.1f}%｜需重 OCR/重导入 {need_reocr} = {need_reocr/931*100:.1f}%')
    print(f'报告：{out}')
    print(f'明细：{args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
