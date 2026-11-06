# -*- coding: utf-8 -*-
"""解析人工抽检结果，计算一致率并生成报告。

用法：
  python kb_check_parse.py                # 解析所有 盲评清单_*.md
  python kb_check_parse.py --batch A      # 只解析 A 批
"""
import json, pathlib, re, sys, datetime, collections

V = pathlib.Path(r'C:\Users\Viver\Desktop\高中数学')
DIR = V / '11_Spotcheck'

# ---------- 载入标注 ----------
ann = {}
for j in (V / '02_Processed' / 'Annotations').glob('gk_*.json'):
    b = json.loads(j.read_text(encoding='utf-8'))
    for it in b.get('items', []):
        ann[it['question_id']] = it['annotation']

titles = {}
for line in (V / '10_Indexes' / '知识点词表.md').read_text(encoding='utf-8').splitlines():
    m = re.match(r'\|\s*`(kp_\d\d_\d\d_[a-z_]+)`\s*\|\s*([^|]+)\|', line)
    if m:
        titles[m.group(1)] = m.group(2).strip()

# ---------- 解析清单 ----------
QID = re.compile(r'###\s+(\d+)\.\s*`(gk_[^`]+)`')
VAL = re.compile(r'^判定[:：]\s*(.*)$')

def norm(v):
    if v is None:
        return ''
    v = str(v).strip().strip('`').strip()
    v = re.sub(r'[。．\.、,，;；]+$', '', v)
    v = v.replace(' ', '').replace('\u3000', '')
    return v

def parse_file(p):
    out = []
    cur = None
    for line in p.read_text(encoding='utf-8').splitlines():
        m = QID.search(line)
        if m:
            cur = m.group(2)
            continue
        if cur:
            mv = VAL.match(line.strip())
            if mv:
                out.append((cur, norm(mv.group(1))))
                cur = None
    return out

batches = sys.argv[sys.argv.index('--batch') + 1] if '--batch' in sys.argv else None
xlsx_path = sys.argv[sys.argv.index('--xlsx') + 1] if '--xlsx' in sys.argv else None

if xlsx_path:
    # 从工作簿读取：任何带 qid 与判定列的表都会被识别
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, data_only=True)
    rows = []
    for sh in wb.sheetnames:
        ws = wb[sh]
        hdr = [str(c.value or '').strip() for c in ws[1]]
        if 'qid' not in hdr:
            continue
        qi = hdr.index('qid')
        vi = None
        for cand in ('你的判定', '判定（校正）', '判定（原始）'):
            if cand in hdr:
                vi = hdr.index(cand)
                break
        if vi is None:
            continue
        for r in range(2, ws.max_row + 1):
            qid = ws.cell(r, qi + 1).value
            val = ws.cell(r, vi + 1).value
            if qid:
                rows.append((sh, str(qid), norm(val)))
    rows = [x for x in rows if x[1] in ann]
else:
    rows = []
    for p in sorted(DIR.glob('盲评清单_*.md')):
        name = p.stem.split('_')[-1]
        if batches and name != batches:
            continue
        for qid, v in parse_file(p):
            rows.append((name, qid, v))

if not rows:
    print('未找到填写的判定（检查 判定： 行是否已写入）')
    sys.exit(0)

# ---------- 统计 ----------
filled = [(b, q, v) for b, q, v in rows if v]
blank = [(b, q, v) for b, q, v in rows if not v]
strict_ok = loose_ok = 0
diffs = []
for b, qid, v in filled:
    mine = (ann.get(qid) or {}).get('kp_primary') or '—'
    got = v.rstrip('?')
    unsure = v.endswith('?')
    if got == mine:
        loose_ok += 1
        if not unsure:
            strict_ok += 1
        else:
            diffs.append((b, qid, mine, v, '带问号但一致'))
    else:
        diffs.append((b, qid, mine, v, '不一致'))

n = len(filled)
print(f'抽取 {len(rows)} 题｜已填 {n}｜未填 {len(blank)}')
if n == 0:
    print('暂无已填判定。请在 盲评清单_*.md 的「判定：」行写入词条 ID 后重跑。')
    sys.exit(0)
print(f'严格一致率 {strict_ok}/{n} = {strict_ok / n * 100:.1f}%')
print(f'宽松一致率 {loose_ok}/{n} = {loose_ok / n * 100:.1f}%')

# 按批
by_batch = collections.Counter()
for b, qid, v in filled:
    if v.rstrip('?') == (ann.get(qid) or {}).get('kp_primary'):
        by_batch[b] += 1
tot_batch = collections.Counter(b for b, _, _ in filled)
print('\n按批：')
for b in sorted(tot_batch):
    print(f'  {b}: {by_batch[b]}/{tot_batch[b]} = {by_batch[b] / tot_batch[b] * 100:.0f}%')

# 按年
yr_ok = collections.Counter()
yr_tot = collections.Counter()
for b, qid, v in filled:
    y = qid.split('_')[1]
    yr_tot[y] += 1
    if v.rstrip('?') == (ann.get(qid) or {}).get('kp_primary'):
        yr_ok[y] += 1
print('\n按年：')
for y in sorted(yr_tot):
    print(f'  {y}: {yr_ok[y]}/{yr_tot[y]}')

# ---------- 报告 ----------
today = datetime.date.today().isoformat()
lines = ['---', 'type: report', f'title: 抽检结果 {today}', f'updated: {today}', '---', '',
         f'# 人工抽检结果（{today}）', '',
         '> 返回 [[首页]] ｜ 方案 [[抽检说明与判定标准]]', '',
         '## 1. 总体', '',
         '| 指标 | 数值 |', '| --- | --- |',
         f'| 抽取 | {len(rows)} |',
         f'| 已判定 | {n} |',
         f'| 未填 | {len(blank)} |',
         f'| **严格一致率**（问号记为不一致） | **{strict_ok / n * 100:.1f}%** |',
         f'| 宽松一致率（问号但正确记为一致） | {loose_ok / n * 100:.1f}% |',
         '', '## 2. 按批', '', '| 批 | 一致/已判 | 一致率 |', '| --- | --- | --- |']
for b in sorted(tot_batch):
    lines.append(f'| {b} | {by_batch[b]}/{tot_batch[b]} | {by_batch[b] / tot_batch[b] * 100:.0f}% |')
lines += ['', '## 3. 按年', '', '| 年份 | 一致/已判 |', '| --- | --- |']
for y in sorted(yr_tot):
    lines.append(f'| {y} | {yr_ok[y]}/{yr_tot[y]} |')
lines += ['', '## 4. 分歧清单', '', '| 批 | qid | 我的 | 你的 | 类型 | 我的理由 |', '| --- | --- | --- | --- | --- | --- |']
for b, qid, mine, got, kind in diffs:
    why = ((ann.get(qid) or {}).get('why') or '').replace('|', '/')
    lines.append(f'| {b} | `{qid}` | `{mine}` | `{got}` | {kind} | {why} |')
if blank:
    lines += ['', '## 5. 未填项', ''] + [f'- `{q}`（{b}）' for b, q, _ in blank]

out = DIR / f'抽检结果_数据_{today}.md'
out.write_text('\n'.join(lines), encoding='utf-8')
print('\n已写:', out)
