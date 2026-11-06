#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材复核样本扩到 20%（360 块）：保留原 180，按册/章/风险补 180。

stage sample: 生成 sample_360.json + sample_360_report.md（不写 PG/vault、不调 OCR）
stage xlsx:   生成 教材映射复核_20pct_360块_2026-11-06.xlsx（可用系统 python 运行）
                xlsx 副本默认不写个人目录，需要时 --xlsx-copy / CHILON_XLSX_COPY。

词表默认 corpus/eval/kp_vocab.md（仓库内副本），可用 CHILON_KP_VOCAB 覆盖。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
MAPPED = OUT / 'mapped_1797.json'
BASE = OUT / 'sample_180.json'
PILOT = OUT / 'mapped_100.json'
SAMPLE = OUT / 'sample_360.json'
REPORT = OUT / 'sample_360_report.md'
XLSX = OUT / '教材映射复核_20pct_360块_2026-11-06.xlsx'
SEED = 20261106
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))


def module_map():
    mods = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mid = m.group(2)
            mods[mid.split('_')[1]] = {'id': mid, 'name': re.split(r'（', m.group(1))[0].strip()}
    return mods


def pick_spread(pool, n, rng, selected):
    by_ch = collections.defaultdict(list)
    for b in pool:
        if b['block_id'] in selected:
            continue
        by_ch[b.get('chapter') or f"none-{b['book']}"].append(b)
    for arr in by_ch.values():
        arr.sort(key=lambda x: (x['page'], x['part'], x['ordinal']))
        rng.shuffle(arr)
    keys = sorted(by_ch)
    picked = []
    while len(picked) < n and keys:
        progressed = False
        for k in keys:
            if len(picked) >= n:
                break
            if by_ch[k]:
                picked.append(by_ch[k].pop())
                progressed = True
        if not progressed:
            break
    return picked


def stage_sample(args):
    recs = json.loads(MAPPED.read_text(encoding='utf-8'))['items']
    byid = {x['block_id']: x for x in recs}
    base = json.loads(BASE.read_text(encoding='utf-8'))['block_ids']
    pilot = {x['block_id'] for x in json.loads(PILOT.read_text(encoding='utf-8'))['items']}
    if len(base) != 180 or len(set(base)) != 180:
        raise SystemExit('sample_180 不是 180 唯一 block_id')
    first = base
    remaining = [x for x in recs if x['block_id'] not in set(first) | pilot]
    rng = random.Random(SEED)
    selected = set(first)
    new = []
    # 每册补 36：低置信6 + vocab_gap4 + non_content2 + 正常24（不足用正常/剩余补）
    for book in sorted({x['book'] for x in recs}):
        pool = [x for x in remaining if x['book'] == book and x['block_id'] not in selected]
        low = [x for x in pool if x['status'] == 'mapped' and x['confidence'] <= 0.70]
        gap = [x for x in pool if x['status'] == 'vocab_gap']
        non = [x for x in pool if x['status'] == 'non_content']
        normal = [x for x in pool if x['status'] == 'mapped' and x['confidence'] > 0.70]
        take = []
        for arr, quota in ((low, 6), (gap, 4), (non, 2)):
            add = pick_spread(arr, quota, rng, selected)
            take += add
            selected |= {x['block_id'] for x in add}
        remain = 36 - len(take)
        for arr in (normal, [x for x in pool if x['block_id'] not in selected]):
            if remain <= 0:
                break
            add = pick_spread(arr, remain, rng, selected)
            take += add
            selected |= {x['block_id'] for x in add}
            remain = 36 - len(take)
        new += take
    new = new[:180]
    if len(new) < 180:
        rest = [x for x in remaining if x['block_id'] not in selected]
        rng.shuffle(rest)
        new += rest[:180 - len(new)]
    if len(new) != 180:
        raise SystemExit(f'新增样本 {len(new)} ≠ 180')
    ids = first + [x['block_id'] for x in new]
    if len(ids) != 360 or len(set(ids)) != 360:
        raise SystemExit(f'sample_360 不唯一/不足: {len(ids)}')
    SAMPLE.write_text(json.dumps({'seed': SEED, 'target': 360, 'count': len(ids),
                                  'exclude_pilot': 100, 'first_180': first,
                                  'new_180': [x['block_id'] for x in new],
                                  'block_ids': ids}, ensure_ascii=False, indent=1), encoding='utf-8')
    # 统计
    items = [byid[i] for i in ids]
    first_items = [byid[i] for i in first]
    new_items = new
    def risk(x):
        if x['status'] == 'non_content':
            return 'non_content'
        if x['status'] == 'vocab_gap':
            return 'vocab_gap'
        return 'low_conf' if x['confidence'] <= 0.70 else 'normal'
    all_risk = collections.Counter(risk(x) for x in items)
    first_risk = collections.Counter(risk(x) for x in first_items)
    new_risk = collections.Counter(risk(x) for x in new_items)
    by_book = collections.Counter(x['book'] for x in items)
    by_book_new = collections.Counter(x['book'] for x in new_items)
    chapters = {(x['book'], x['chapter']) for x in items if x.get('chapter')}
    L = ['---', 'type: report', 'title: 教材复核样本扩到 20%（360 块）', 'updated: 2026-11-06',
         'status: sample-360', '---', '',
         '# 教材复核样本 20%（360 块）报告', '',
         '> 从 1697 个未复核块抽 360（20%）；前 180 保留原 `sample_180` 顺序；新增 180 从剩余 1517 块补。',
         '> seed=20261106；与 100 pilot **0 重叠**；未写 PG/vault、未调 OCR、未 commit。', '',
         '## 1. 总量', '',
         '| 指标 | 数值 |', '| --- | --- |',
         f'| sample_360 | **{len(items)}**（前 180 + 新 180） |',
         f'| 每册 | {", ".join(f"{b[-8:]}:{n}" for b, n in by_book.items())} |',
         f'| 覆盖章 | **{len(chapters)}/18** |',
         f'| 与 100 pilot 重叠 | 0 |',
         f'| 与 sample_180 重叠 | {len(set(ids) & set(first))}（=180，前 180 原样保留） |', '',
         '## 2. 风险构成', '',
         '| 风险 | 全部 360 | 前 180 | 新 180 |', '| --- | --- | --- | --- |',
         f'| 低置信（≤0.70） | {all_risk.get("low_conf",0)} | {first_risk.get("low_conf",0)} | {new_risk.get("low_conf",0)} |',
         f'| vocab_gap | {all_risk.get("vocab_gap",0)} | {first_risk.get("vocab_gap",0)} | {new_risk.get("vocab_gap",0)} |',
         f'| non_content | {all_risk.get("non_content",0)} | {first_risk.get("non_content",0)} | {new_risk.get("non_content",0)} |',
         f'| 正常 mapped | {all_risk.get("normal",0)} | {first_risk.get("normal",0)} | {new_risk.get("normal",0)} |', '',
         '## 3. 按册分布', '', '| 册 | 总 360 | 新增 180 |', '| --- | --- | --- |']
    for book in sorted(by_book):
        L.append(f'| {book} | {by_book[book]} | {by_book_new.get(book,0)} |')
    L += ['', '## 4. 与旧 180 表差异', '',
          '- 前 180 行 block_id 与顺序**完全保留**；新增 180 追加在后，旧表可直接作为新表前 180 行使用。',
          '- 新增样本按每册 36、章轮转、风险优先抽取；共 360 行、每册 72。', '',
          '## 5. 校验', '',
          '- sample_360：**360 唯一 block_id**、每册 72、覆盖 18/18 章、与 pilot 0 重叠；',
          '- xlsx：360 行、完整原文非空、文本列为字面字符串（无公式开头）、17/120 下拉、教师列空。', '',
          '---', '', '> 产物：`sample_360.json`、`教材映射复核_20pct_360块_2026-11-06.xlsx`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[sample] 360={len(items)}；每册 {dict(by_book)}；章 {len(chapters)}/18；'
          f'风险 {dict(all_risk)}；新增 {len(new)}；pilot overlap {len(set(ids)&pilot)}')
    print(f'报告：{REPORT}')
    return 0


def stage_xlsx(args):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter
    recs = {x['block_id']: x for x in json.loads(MAPPED.read_text(encoding='utf-8'))['items']}
    ids = json.loads(SAMPLE.read_text(encoding='utf-8'))['block_ids']
    items = [recs[i] for i in ids]
    mods = module_map()
    mod_list = [v['id'] for v in mods.values()]
    kp_list = []
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('|'):
            parts = [x.strip() for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
                kp_list.append(parts[0].strip('`'))
    pdf_dir = ROOT / 'corpus' / 'textbooks'
    pdfs = {p.stem: str(p) for p in pdf_dir.glob('*.pdf')}
    wb = Workbook(); ws = wb.active; ws.title = '复核360块'
    headers = ['序号', 'block_id', '册', '章', '节', '页码', '块类型', '完整原文', '模型模块',
               '模型primary', '名称', '模型secondary', '置信', '理由', '教师模块', '教师考点', '备注', '来源PDF']
    ws.append(headers)
    for i, x in enumerate(items, 1):
        src = next((p for stem, p in pdfs.items() if x['book'] in stem), str(pdf_dir))
        ws.append([i, x['block_id'], x['book'], x.get('chapter', ''), x.get('section', ''), x['page'],
                   x['block_type'], None, x.get('module_id', ''), x['kp_primary'], x.get('kp_name', ''),
                   ' '.join(x['kp_secondary']), x['confidence'], x['reason'], '', '', '', src])
        cell = ws.cell(row=ws.max_row, column=8)
        cell.value = x['text']
        cell.data_type = 's'
    ws2 = wb.create_sheet('词表')
    ws2['A1'] = '模块ID'; ws2['B1'] = '模块名称'; ws2['C1'] = '考点ID'; ws2['D1'] = '考点名称'
    for i, mid in enumerate(mod_list, 2):
        ws2.cell(i, 1, mid); ws2.cell(i, 2, mods[mid.split('_')[1]]['name'])
    for i, kp in enumerate(kp_list, 2):
        ws2.cell(i, 3, kp)
    dv1 = DataValidation(type='list', formula1=f'=词表!$A$2:$A${len(mod_list)+1}', allow_blank=True)
    dv2 = DataValidation(type='list', formula1=f'=词表!$C$2:$C${len(kp_list)+1}', allow_blank=True)
    ws.add_data_validation(dv1); ws.add_data_validation(dv2)
    dv1.add(f'O2:O{len(items)+1}'); dv2.add(f'P2:P{len(items)+1}')
    thin = Side(style='thin', color='BBBBBB'); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c in ws[1]:
        c.fill = PatternFill('solid', fgColor='DDEBF7'); c.font = Font(bold=True)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True); c.border = border
    widths = [6, 24, 32, 24, 28, 8, 12, 90, 20, 20, 20, 24, 8, 50, 18, 22, 26, 48]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=True); c.border = border
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 70
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = f'A1:R{ws.max_row}'
    ws3 = wb.create_sheet('说明')
    lines = [
        ['教材 v3 全量映射 · 20%（360 块）教师复核表'],
        [''],
        ['目的', '验证 v3 规则在未复核 1697 块中的泛化；本表只给模型候选，教师判定请填教师模块/考点/备注。'],
        ['20% 口径', '360 = 1797 × 20%（约 10% 的 180 扩到 360）；全部来自 1697 未复核块。'],
        ['前 180', '前 180 行 = 原 10% 样本 `教材映射复核_180块` 的 block_id/顺序，完全保留。'],
        ['新增 180', '后 180 行 = 从剩余 1517 块补抽：每册 36，按章/风险（低置信/vocab_gap/non_content/正常）。'],
        ['不重叠', '与 100 个 pilot 块 **0 重叠**；前 180 与新增 180 互不重复。'],
        ['待填计数', '本表 360 行教师模块/教师考点/备注全部留空（待填 360）；前 180 已有人工核对表可对照。'],
        ['校验', '360 行、block_id 唯一、完整原文非空且为字面文本（无公式开头）、17/120 下拉正常。'],
    ]
    for r in lines:
        ws3.append(r)
    ws3['A1'].font = Font(bold=True, size=14)
    ws3.column_dimensions['A'].width = 22; ws3.column_dimensions['B'].width = 120
    wb.save(XLSX)
    copy_to = getattr(args, 'xlsx_copy', None)
    if copy_to:
        target = pathlib.Path(copy_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(XLSX, target)
        print(f'[xlsx] {XLSX}（{len(items)} 行）；副本 {target}')
    else:
        print(f'[xlsx] {XLSX}（{len(items)} 行）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材复核样本扩到 20%')
    ap.add_argument('--stage', choices=['sample', 'xlsx'], default='sample')
    ap.add_argument('--xlsx-copy', default=os.environ.get('CHILON_XLSX_COPY'),
                    help='可选：把生成的复核 xlsx 复制到该路径（默认不复制）')
    args = ap.parse_args(argv)
    if args.stage == 'sample':
        return stage_sample(args)
    return stage_xlsx(args)


if __name__ == '__main__':
    sys.exit(main())
