# -*- coding: utf-8 -*-
"""解析第三轮抽检（模块 + 考点双层），输出数据报告 + 错位诊断。

用法：python kb_check_round3.py "路径\\抽检_第三轮_2026-11-06_教师已填.xlsx"
数据报告写到 抽检结果_第三轮_数据_<日期>.md，人工结论另写，不被覆盖。
"""
import json, pathlib, re, sys, collections, datetime
from openpyxl import load_workbook

V = pathlib.Path(r'C:\Users\Viver\Desktop\高中数学')
OUT = V / '11_Spotcheck'
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (OUT / '抽检_第三轮_2026-11-06.xlsx')

ann = {}
for j in (V / '02_Processed' / 'Annotations').glob('gk_*.json'):
    b = json.loads(j.read_text(encoding='utf-8'))
    for it in b.get('items', []):
        ann[it['question_id']] = it['annotation']

MODS = []
for line in (V / '10_Indexes' / '知识点词表.md').read_text(encoding='utf-8').splitlines():
    m = re.match(r'^##\s*(\d+)\.\s*(.+?)[（(].*?`(kp_\d\d_[a-z_]+)`', line)
    if m:
        MODS.append((m.group(3), re.sub(r'^旧课标[，,]\s*', '', m.group(2)).strip()))
MOD_NAME = dict(MODS)
MOD_NUM = {mid.split('_')[1]: mid for mid, _ in MODS}

titles = {}
for line in (V / '10_Indexes' / '知识点词表.md').read_text(encoding='utf-8').splitlines():
    m = re.match(r'\|\s*`(kp_\d\d_\d\d_[a-z_]+)`\s*\|\s*([^|]+)\|', line)
    if m:
        titles[m.group(1)] = m.group(2).strip()

def module_of(kp):
    if not kp or not kp.startswith('kp_'):
        return ''
    return MOD_NUM.get(kp.split('_')[1], '')

def norm(v):
    if v is None:
        return ''
    return str(v).strip().strip('`').strip().replace(' ', '').replace('\u3000', '')

wb = load_workbook(SRC, data_only=True)
ws = wb['抽检清单']
hdr = [str(c.value or '').strip() for c in ws[1]]
def col(name):
    for i, h in enumerate(hdr):
        if h.startswith(name):
            return i
    raise KeyError(name)
ci_q, ci_m, ci_k = col('qid'), col('模块'), col('具体考点')
rows = []
for r in range(2, ws.max_row + 1):
    qid = ws.cell(r, ci_q + 1).value
    if not qid:
        continue
    rows.append((ws.cell(r, 1).value, str(qid),
                 norm(ws.cell(r, ci_m + 1).value), norm(ws.cell(r, ci_k + 1).value)))

# 错位诊断
print('=== 错位诊断（模块列）===')
shift_scores = {}
for sh in range(-2, 3):
    ok = tot = 0
    for i, (seq, qid, m, k) in enumerate(rows):
        j = i + sh
        if 0 <= j < len(rows):
            tot += 1
            if m and m == module_of(ann.get(rows[j][1], {}).get('kp_primary')):
                ok += 1
    pct = ok / tot * 100 if tot else 0
    shift_scores[sh] = pct
    print(f'  偏移 {sh:+d}: {ok}/{tot} = {pct:.1f}%')
peak = max((s for s in shift_scores if abs(s) == 1), key=lambda s: shift_scores[s])
if shift_scores[peak] > 20:
    print(f'  ⚠️ 可能整列粘贴错位：偏移 {peak:+d} 时跳到 {shift_scores[peak]:.1f}%，请核对前 3 行')

# 统计
mod_ok = mod_n = 0
kp_ok = kp_n = 0
mod_diffs, gran, noprim = [], [], []
for seq, qid, m, k in rows:
    a = ann.get(qid, {})
    mine_kp = a.get('kp_primary') or ''
    mine_mod = module_of(mine_kp)
    if not mine_kp:
        noprim.append((seq, qid))
    if not m:
        continue
    mod_n += 1
    if m == mine_mod:
        mod_ok += 1
    elif m in ('无', '无归属'):
        mod_diffs.append((seq, qid, mine_mod, mine_kp, m, k, '你判无法归类'))
    else:
        mod_diffs.append((seq, qid, mine_mod, mine_kp, m, k, '模块不一致'))
    if k:
        kp_n += 1
        if k == mine_kp:
            kp_ok += 1
        elif module_of(k) == mine_mod and m == mine_mod:
            gran.append((seq, qid, mine_kp, k))

print()
if mod_n:
    print(f'已填模块 {mod_n}/{len(rows)}｜模块一致 {mod_ok} = {mod_ok / mod_n * 100:.1f}%')
    print(f'已填考点 {kp_n}｜考点一致 {kp_ok} = {kp_ok / kp_n * 100:.1f}%' if kp_n else '考点未填')
    print(f'模块级分歧 {len(mod_diffs)}｜粒度差异（模块同、考点不同）{len(gran)}｜我判无归属 {len(noprim)}')
else:
    print('尚未填写模块判定，未生成报告。')
    sys.exit(0)

today = datetime.date.today().isoformat()
p = OUT / f'抽检结果_第三轮_数据_{today}.md'
L = ['---', 'type: data', f'title: 抽检数据（第三轮）{today}', f'updated: {today}', '---', '',
     '# 抽检数据（第三轮 · 原始结果）', '',
     f'> 来源：`{SRC.name}`｜结论见 [[抽检结果_第三轮_2026-11-06]]', '',
     '## 1. 总体', '', '| 指标 | 结果 | 目标 |', '| --- | --- | --- |',
     f'| 有效判定 | {mod_n}/{len(rows)} | {len(rows)} |',
     f'| **模块一致率** | **{mod_ok / mod_n * 100:.1f}%**（{mod_ok}/{mod_n}） | ≥90% |',
     f'| 考点一致率（参考） | {kp_ok}/{kp_n} = {kp_ok / kp_n * 100:.1f}% | — |',
     f'| 粒度差异 | {len(gran)} | 单列，不算错 |',
     f'| 模块级分歧 | {len(mod_diffs)} | 逐条复核 |',
     f'| 我判无归属 | {len(noprim)} | 逐条复核 |',
     '', '## 2. 错位诊断', '', '| 偏移 | 模块一致率 |', '| --- | --- |']
for s in sorted(shift_scores):
    L.append(f'| {s:+d} | {shift_scores[s]:.1f}% |')
L += ['', '## 3. 模块级分歧', '',
      '| 题 | qid | 我的模块 | 我的考点 | 你的模块 | 你的考点 | 类型 |',
      '| --- | --- | --- | --- | --- | --- | --- |']
for seq, qid, mm, mk, tm, tk, kind in mod_diffs:
    L.append(f'| {seq} | `{qid}` | {MOD_NAME.get(mm, "无归属")} | {titles.get(mk, "—")} | '
             f'{MOD_NAME.get(tm, tm)} | {titles.get(tk, "—")} | {kind} |')
L += ['', '## 4. 粒度差异（模块相同、考点不同）', '', '| 题 | qid | 我的考点 | 你的考点 |', '| --- | --- | --- | --- |']
for seq, qid, mk, tk in gran:
    L.append(f'| {seq} | `{qid}` | {titles.get(mk, mk)} | {titles.get(tk, tk)} |')
if noprim:
    L += ['', '## 5. 我判无归属', '', '| 题 | qid |', '| --- | --- |']
    for seq, qid in noprim:
        L.append(f'| {seq} | `{qid}` |')
p.write_text('\n'.join(L) + '\n', encoding='utf-8')
print('已写数据报告:', p.name)
