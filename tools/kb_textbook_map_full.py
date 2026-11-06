#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材映射 v3 全量 1797 + 180 块复核样本（只读，不写 PG/vault、不调 OCR）。

阶段：
  --stage map   用 v3 规则映射全部 1797 块（映射阶段不读教师标签）；
                mapped_1797.json / batch、sample_180.json、full_mapping_report.md
  --stage xlsx  由 sample_180 + mapped_1797 生成教师复核 xlsx（需 openpyxl，可用系统 python）；
                xlsx 副本默认不写个人目录，需要时 --xlsx-copy / CHILON_XLSX_COPY。

词表默认 corpus/eval/kp_vocab.md（仓库内副本），可用 CHILON_KP_VOCAB 覆盖。
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import pathlib
import random
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
BLOCKS = OUT / 'blocks_1797_with_structure.json'
DICT = OUT / 'section_kp_dictionary.json'
PILOT_MAPPED = OUT / 'mapped_100.json'
MAPPED = OUT / 'mapped_1797.json'
BATCH = OUT / 'mapped_1797_batch.txt'
SAMPLE = OUT / 'sample_180.json'
REPORT = OUT / 'full_mapping_report.md'
XLSX = OUT / '教材映射复核_180块_2026-11-06.xlsx'
SEED = 20261106
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))


def load_modules():
    spec = importlib.util.spec_from_file_location('v3', ROOT / 'tools' / 'kb_textbook_map_v3.py')
    v3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v3)
    tb1, mockann = v3.load()
    return v3, tb1, mockann


def module_map():
    mods = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mid = m.group(2)
            mods[mid.split('_')[1]] = {'id': mid, 'name': re.split(r'（', m.group(1))[0].strip()}
    return mods


def derive_ids(blocks, pilot_items):
    """由 pilot 映射反推 book→B 序号，再给所有块生成稳定 block_id。"""
    book_idx = {}
    for x in pilot_items:
        m = re.match(r'TB-B(\d+)-', x['block_id'])
        if m:
            book_idx[x['book']] = int(m.group(1))
    for book in sorted({b['book'] for b in blocks}):
        if book not in book_idx:
            raise SystemExit(f'无法推断 book 序号: {book}')
    by_chunk = {x['chunk_id']: x for x in pilot_items}
    id_map = {}
    for b in blocks:
        bid = by_chunk.get(b['chunk_id'], {}).get('block_id')
        if not bid:
            bid = f"TB-B{book_idx[b['book']]}-{b['page']:04d}-{b['part']}-{b['chunk_key']}"
        id_map[b['chunk_id']] = bid
    return id_map


def pick_spread(pool, n, rng, selected):
    """按 chapter_num 轮转抽 n 个，尽量覆盖章。"""
    by_ch = collections.defaultdict(list)
    for b in pool:
        if b['block_id'] in selected:
            continue
        by_ch[b.get('chapter_num') or 0].append(b)
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


def stage_map(args):
    v3, tb1, mockann = load_modules()
    vocab = mockann.load_vocab()
    blocks = json.loads(BLOCKS.read_text(encoding='utf-8'))['blocks']
    dictionary = json.loads(DICT.read_text(encoding='utf-8'))
    pilot_items = json.loads(PILOT_MAPPED.read_text(encoding='utf-8'))['items']
    id_map = derive_ids(blocks, pilot_items)
    mods = module_map()
    recs = []
    for b in blocks:
        rec = v3.map_block(b, vocab, mockann, tb1, dictionary)
        rec['block_id'] = id_map[b['chunk_id']]
        if rec.get('module') and rec['module'] in mods:
            rec['module_id'] = mods[rec['module']]['id']
            rec['module_name'] = mods[rec['module']]['name']
        else:
            rec['module_id'] = ''
            rec['module_name'] = ''
        recs.append(rec)
    MAPPED.write_text(json.dumps({'count': len(recs), 'rules': 'chapter-module + section_kp dictionary + body keywords',
                                  'items': recs}, ensure_ascii=False, indent=1), encoding='utf-8')
    BATCH.write_text('\n'.join(
        f"{i:04d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['chapter']}|{x['section']}|"
        f"{x['status']}|{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}"
        for i, x in enumerate(recs, 1)) + '\n', encoding='utf-8')
    # 抽样 180：排除 pilot 100
    pilot_ids = {x['block_id'] for x in pilot_items}
    nonpilot = [x for x in recs if x['block_id'] not in pilot_ids]
    rng = random.Random(SEED)
    selected = set()
    sample = []
    # 每册 36：低置信6 + vocab_gap4 + non_content2 + 正常24（不足则用正常内容补）
    for book in sorted({x['book'] for x in recs}):
        pool = [x for x in nonpilot if x['book'] == book]
        low = [x for x in pool if x['status'] == 'mapped' and x['confidence'] <= 0.70]
        gap = [x for x in pool if x['status'] == 'vocab_gap']
        non = [x for x in pool if x['status'] == 'non_content']
        normal = [x for x in pool if x['status'] == 'mapped' and x['confidence'] > 0.70]
        take = []
        take += pick_spread(low, 6, rng, selected)
        selected |= {x['block_id'] for x in take}
        take += pick_spread(gap, 4, rng, selected)
        selected |= {x['block_id'] for x in take}
        take += pick_spread(non, 2, rng, selected)
        selected |= {x['block_id'] for x in take}
        remain = 36 - len(take)
        for arr in (normal, [x for x in pool if x not in take]):
            if remain <= 0:
                break
            add = pick_spread(arr, remain, rng, selected)
            take += add
            selected |= {x['block_id'] for x in add}
            remain = 36 - len(take)
        sample.extend(take)
    # 保险补足/裁切（正常应 180）
    sample = sample[:180]
    if len(sample) < 180:
        rest = [x for x in nonpilot if x['block_id'] not in {y['block_id'] for y in sample}]
        rng.shuffle(rest)
        sample += rest[:180 - len(sample)]
    SAMPLE.write_text(json.dumps({'seed': SEED, 'target': 180, 'count': len(sample),
                                  'exclude_pilot': 100, 'block_ids': [x['block_id'] for x in sample]},
                                 ensure_ascii=False, indent=1), encoding='utf-8')
    # 统计
    status = collections.Counter(x['status'] for x in recs)
    low = sum(1 for x in recs if x['status'] == 'mapped' and x['confidence'] <= 0.70)
    ch_cov = sum(1 for x in recs if x.get('chapter'))
    sec_cov = sum(1 for x in recs if x.get('section'))
    by_book = collections.Counter(x['book'] for x in recs)
    by_book_status = collections.defaultdict(collections.Counter)
    for x in recs:
        by_book_status[x['book']][x['status']] += 1
    by_ch = collections.Counter((x['book'], x.get('chapter_num'), x.get('chapter')) for x in recs if x.get('chapter'))
    sample_status = collections.Counter(x['status'] for x in sample)
    sample_book = collections.Counter(x['book'] for x in sample)
    L = ['---', 'type: report', 'title: 教材 v3 全量 1797 映射报告', 'updated: 2026-11-06',
         'status: full-mapping', '---', '',
         '# 教材 v3 全量 1797 映射报告', '',
         '> 规则：chapter 限定模块 + 93 条 section→kp 词典 + 正文关键词；映射阶段未读教师标签。  ',
         '> 只读 OCR 文本；不写 PG/vault、不调 OCR、未 commit。', '',
         '## 1. 覆盖', '',
         '| 指标 | 数值 |', '| --- | --- |',
         f'| 教材块 | **{len(recs)}/1797** |',
         f'| chapter 覆盖 | **{ch_cov}/1797 = {ch_cov/1797*100:.1f}%** |',
         f'| section 覆盖 | **{sec_cov}/1797 = {sec_cov/1797*100:.1f}%** |',
         f'| mapped primary | **{status.get("mapped",0)}** |',
         f'| non_content | **{status.get("non_content",0)}** |',
         f'| vocab_gap | **{status.get("vocab_gap",0)}** |',
         f'| 低置信（≤0.70，mapped） | **{low}** |', '',
         '### 按册', '', '| 册 | mapped | non_content | vocab_gap | 总 |', '| --- | --- | --- | --- | --- |']
    for book in sorted(by_book):
        c = by_book_status[book]
        L.append(f'| {book} | {c.get("mapped",0)} | {c.get("non_content",0)} | {c.get("vocab_gap",0)} | {by_book[book]} |')
    L += ['', '### 按章（前 30）', '', '| 册/章 | 块数 |', '| --- | --- |']
    for (book, num, ch), n in by_ch.most_common(30):
        L.append(f'| {book[-8:]}/第{num}章 {ch} | {n} |')
    L += ['', '## 2. 180 块复核样本（来自 1697 未复核块）', '',
          f'- 目标 **180**，实际 **{len(sample)}**；seed={SEED}；**排除 100 pilot**（不重叠）。',
          f'- 每册 36：低置信 6 + vocab_gap 4 + non_content 2 + 正常内容 24（不足则以正常内容补）。',
          f'- 样本状态：{dict(sample_status)}',
          f'- 样本按册：{dict(sample_book)}',
          f'- 复核表：`{XLSX.name}`（教师模块/考点 17/120 下拉，教师列留空）。', '',
          '## 3. 结论', '',
          '- 全量映射覆盖 1797；chapter/section 覆盖见上；primary 以 mapped 为主，non_content/vocab_gap 保留显式状态。',
          '- 180 块为未复核 1697 块的约 10%，按册/章+风险（低置信、vocab_gap、non_content、正常）抽取，避免与 100 pilot 重叠。', '',
          '---', '', '> 产物：`mapped_1797.json`、`mapped_1797_batch.txt`、`sample_180.json`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[full] mapped {len(recs)}；mapped {status.get("mapped",0)}；non_content {status.get("non_content",0)}；'
          f'vocab_gap {status.get("vocab_gap",0)}；low {low}；sample {len(sample)}/{180}')
    print(f'报告：{REPORT}')
    return 0


def stage_xlsx(args):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter
    recs = {x['block_id']: x for x in json.loads(MAPPED.read_text(encoding='utf-8'))['items']}
    ids = json.loads(SAMPLE.read_text(encoding='utf-8'))['block_ids']
    items = [recs[i] for i in ids if i in recs]
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
    wb = Workbook(); ws = wb.active; ws.title = '复核180块'
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
    # 词表隐藏 sheet（17/120 下拉）
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
        ['教材 v3 全量映射 · 180 块教师复核表'],
        [''],
        ['目的', '验证 v3 规则在未复核 1697 块中的泛化质量；本表只给模型候选，教师判定请填教师模块/考点/备注。'],
        ['为什么是 180', '1797 总块 − 100 已核 pilot = 1697 未复核；抽 180 约 10%，seed=20261106。'],
        ['不与 pilot 重叠', '本 180 块从排除 100 个 pilot block_id 后的池中抽取，和 pilot 表无重叠。'],
        ['分层', '按 5 册各 36 块；每册含低置信 6、vocab_gap 4、non_content 2、正常内容 24（不足用正常补）。'],
        ['字段', '模型模块/模型primary/名称/模型secondary/置信/理由为模型输出；教师模块/考点/备注请填，可留空。'],
        ['下拉', '教师模块 17 项、教师考点 120 项，来自词表 sheet；完整原文未截断。'],
    ]
    for r in lines:
        ws3.append(r)
    ws3['A1'].font = Font(bold=True, size=14)
    ws3.column_dimensions['A'].width = 22; ws3.column_dimensions['B'].width = 110
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
    ap = argparse.ArgumentParser(description='教材 v3 全量 1797 + 180 块复核')
    ap.add_argument('--stage', choices=['map', 'xlsx'], default='map')
    ap.add_argument('--xlsx-copy', default=os.environ.get('CHILON_XLSX_COPY'),
                    help='可选：把生成的教师复核 xlsx 复制到该路径（默认不复制）')
    args = ap.parse_args(argv)
    if args.stage == 'map':
        return stage_map(args)
    return stage_xlsx(args)


if __name__ == '__main__':
    sys.exit(main())
