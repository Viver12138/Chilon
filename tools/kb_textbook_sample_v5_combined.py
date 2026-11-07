#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""组合复核表（v5）：剩余非-pilot model 块抽 20% + pilot 100 全量回采，合成一张教师表。

口径：
  - 池 = reviewed 中 review_status=model 的块（教师 648 已排除）；
  - pilot 100 = sample_100.json 的块（历史 pilot，本轮全量回采）；
  - 抽样池 = model − pilot；抽 percent%（默认 20%，约 210 条），稀有状态（vocab_gap/non_content）全量；
  - 合并 = 抽样 + pilot 100，去重，按 册→页→part→ordinal 排序；
  - xlsx 增加「来源」列：`20%抽样` / `pilot100回采`；教师列留空、17/120 下拉。
不连 DB、不写 vault、不调 OCR。
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
SAMPLE = OUT / 'sample_100.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
BOOK_ORDER = ['必修第一册', '必修第二册', '选择性必修第一册', '选择性必修第二册', '选择性必修第三册']


def die(msg):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(2)


def book_key(title):
    for s in sorted(BOOK_ORDER, key=len, reverse=True):
        if title.endswith(s):
            return s
    return title


def risk_of(x):
    if x.get('status') == 'non_content':
        return 'non_content'
    if x.get('status') == 'vocab_gap':
        return 'vocab_gap'
    return 'low_conf' if (x.get('confidence') or 0) <= 0.70 else 'normal'


def pick_spread(pool, n, rng):
    by_ch = collections.defaultdict(list)
    for x in pool:
        by_ch[(book_key(x['book']), x.get('chapter_num') or 0, x.get('chapter') or '')].append(x)
    for arr in by_ch.values():
        arr.sort(key=lambda x: (x['page'], x.get('part') or 0, x.get('ordinal') or 0))
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


def allocate(total, groups):
    size = sum(groups.values())
    if size == 0 or total == 0:
        return {k: 0 for k in groups}
    raw = {k: total * v / size for k, v in groups.items()}
    alloc = {k: min(groups[k], int(math.floor(raw[k]))) for k in groups}
    left = total - sum(alloc.values())
    order = sorted(groups, key=lambda k: (-(raw[k] - math.floor(raw[k])), k))
    while left > 0:
        progressed = False
        for k in order:
            if left <= 0:
                break
            if alloc[k] < groups[k]:
                alloc[k] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return alloc


def load_vocab():
    mods, kps = {}, {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mods[m.group(2)] = re.split(r'（', m.group(1))[0].strip()
        if line.strip().startswith('|'):
            parts = [x.strip().strip('`') for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0]):
                kps[parts[0]] = parts[1]
    return mods, kps


def build(args):
    reviewed = json.loads(pathlib.Path(args.reviewed).read_text(encoding='utf-8'))['items']
    mapped_v = {x['block_id']: x for x in json.loads(pathlib.Path(args.mapped).read_text(encoding='utf-8'))['items']}
    by_chunk = {x['chunk_id']: x['block_id'] for x in mapped_v.values()}
    pilot_ids = {by_chunk[b['chunk_id']] for b in json.loads(SAMPLE.read_text(encoding='utf-8'))['blocks']
                 if b['chunk_id'] in by_chunk}
    byid = {x['block_id']: x for x in reviewed}
    model = [x for x in reviewed if x.get('review_status') == 'model']
    teacher_ids = {x['block_id'] for x in reviewed if x.get('review_status') == 'teacher'}
    if getattr(args, 'full_census', False):
        rows = [{**x, 'sample_source': '全量终检'} for x in model]
        rows.sort(key=lambda x: (BOOK_ORDER.index(book_key(x['book'])), x['page'],
                                 x.get('part') or 0, x.get('ordinal') or 0))
        meta = {'seed': args.seed, 'percent': 100.0, 'model': len(model),
                'teacher': len(teacher_ids), 'sampled_pool': len(model),
                'sample_target': len(rows), 'pilot': 0, 'total': len(rows),
                'full_census': True,
                'sample_risk': dict(collections.Counter(risk_of(x) for x in rows)),
                'pilot_risk': {},
                'by_book': dict(collections.Counter(book_key(x['book']) for x in rows)),
                'block_ids': [x['block_id'] for x in rows]}
        return rows, meta
    sampled_pool = [x for x in model if x['block_id'] not in pilot_ids]
    # pilot 块只有仍是 model 时才需要回采（已复核的 pilot 不再进表）
    pilot_model_ids = {i for i in pilot_ids if i in byid and byid[i].get('review_status') == 'model'}
    pilot_pool = [byid[i] for i in sorted(pilot_model_ids)]
    if len(pilot_pool) != len(pilot_model_ids):
        die(f'pilot 块缺失：{len(pilot_model_ids) - len(pilot_pool)}')
    if set(pilot_ids) & teacher_ids:
        pass  # pilot 已复核时不再回采，属正常

    target = math.ceil(len(sampled_pool) * args.percent / 100.0)
    rng = random.Random(args.seed)
    gap = [x for x in sampled_pool if x.get('status') == 'vocab_gap']
    non = [x for x in sampled_pool if x.get('status') == 'non_content']
    mapped = [x for x in sampled_pool if x.get('status') == 'mapped']
    rare = gap + non
    mapped_budget = max(0, target - len(rare))
    by_book = collections.defaultdict(list)
    for x in mapped:
        by_book[book_key(x['book'])].append(x)
    alloc = allocate(mapped_budget, {b: len(v) for b, v in by_book.items()})
    chosen = []
    chosen_ids = {x['block_id'] for x in rare}
    for b in sorted(alloc, key=BOOK_ORDER.index):
        pool = [x for x in by_book[b] if x['block_id'] not in chosen_ids]
        low = [x for x in pool if (x.get('confidence') or 0) <= 0.70]
        normal = [x for x in pool if (x.get('confidence') or 0) > 0.70]
        n = min(alloc[b], len(pool))
        low_q = 0
        if low and n > 0:
            low_q = min(max(1, round(n * len(low) / len(pool))), len(low), n)
        take = pick_spread(low, low_q, rng)
        chosen_ids |= {x['block_id'] for x in take}
        take += pick_spread(normal, n - low_q, rng)
        chosen_ids |= {x['block_id'] for x in take}
        need = n - len(take)
        if need > 0:
            rest = [x for x in pool if x['block_id'] not in chosen_ids]
            rng.shuffle(rest)
            take += rest[:need]
            chosen_ids |= {x['block_id'] for x in take}
        chosen += take
    if len(rare) + len(chosen) < target:
        rest = [x for x in mapped if x['block_id'] not in chosen_ids]
        rng.shuffle(rest)
        chosen += rest[:target - len(rare) - len(chosen)]
        chosen_ids |= {x['block_id'] for x in chosen}
    if len(rare) + len(chosen) != target:
        die(f'抽样数异常 {len(rare) + len(chosen)} != {target}')
    rows = []
    for x in rare + chosen:
        rows.append({**x, 'sample_source': '20%抽样'})
    for x in pilot_pool:
        rows.append({**x, 'sample_source': 'pilot100回采'})
    if len(rows) != target + len(pilot_pool) or len({r['block_id'] for r in rows}) != len(rows):
        die('合并后重复或数量异常')
    rows.sort(key=lambda x: (BOOK_ORDER.index(book_key(x['book'])), x['page'],
                             x.get('part') or 0, x.get('ordinal') or 0))
    meta = {
        'seed': args.seed, 'percent': args.percent,
        'model': len(model), 'teacher': len(teacher_ids),
        'sampled_pool': len(sampled_pool), 'sample_target': target,
        'pilot': len(pilot_pool), 'total': len(rows),
        'sample_risk': dict(collections.Counter(risk_of(x) for x in rows if x['sample_source'] == '20%抽样')),
        'pilot_risk': dict(collections.Counter(risk_of(x) for x in rows if x['sample_source'] == 'pilot100回采')),
        'by_book': dict(collections.Counter(book_key(x['book']) for x in rows)),
        'block_ids': [x['block_id'] for x in rows],
    }
    return rows, meta


def module_map():
    mods = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mods[m.group(2)] = re.split(r'（', m.group(1))[0].strip()
    return mods


def write_xlsx(rows, meta, args):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter
    mapped_v = {x['block_id']: x for x in json.loads(pathlib.Path(args.mapped).read_text(encoding='utf-8'))['items']}
    v4_path = pathlib.Path(getattr(args, 'prev_mapped', str(OUT / 'mapped_1797_v4.json')))
    v4 = {x['block_id']: x for x in json.loads(v4_path.read_text(encoding='utf-8'))['items']} if v4_path.exists() else {}
    mods = module_map()
    kp_list = []
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('|'):
            parts = [x.strip() for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
                kp_list.append(parts[0].strip('`'))
    pdf_dir = ROOT / 'corpus' / 'textbooks'
    pdfs = {p.stem: str(p) for p in pdf_dir.glob('*.pdf')}
    wb = Workbook(); ws = wb.active
    label = getattr(args, 'rule_label', 'v5')
    if meta.get('full_census'):
        ws.title = f'复核{label}_full'
    else:
        ws.title = f'复核{label}_20pct' + ('_pilot' if meta['pilot'] else '')
    rule_l = getattr(args, 'rule_label', 'v5')
    prev_l = getattr(args, 'prev_label', 'v4')
    headers = ['序号', '来源', 'block_id', '册', '章', '节', '页码', '块类型', '完整原文',
               '模型模块', '模型primary', '名称', '模型secondary', '置信', '理由',
               f'{rule_l}规则', f'{prev_l}模型primary', '教师模块', '教师考点', '备注', '来源PDF']
    ws.append(headers)
    for i, x in enumerate(rows, 1):
        mv = mapped_v.get(x['block_id'], {})
        src = next((p for stem, p in pdfs.items() if x['book'] in stem), str(pdf_dir))
        ws.append([i, x['sample_source'], x['block_id'], x['book'], x.get('chapter', ''),
                   x.get('section', ''), x['page'], x['block_type'], None,
                   x.get('module_id', ''), x['kp_primary'], x.get('kp_name', ''),
                   ' '.join(x.get('kp_secondary') or []), x['confidence'], x['reason'],
                   mv.get('rule', ''), v4.get(x['block_id'], {}).get('kp_primary', ''),
                   '', '', '', src])
        cell = ws.cell(row=ws.max_row, column=9)
        cell.value = x['text']
        cell.data_type = 's'
    ws2 = wb.create_sheet('词表')
    ws2['A1'] = '模块ID'; ws2['B1'] = '模块名称'; ws2['C1'] = '考点ID'; ws2['D1'] = '考点名称'
    mod_list = list(mods)
    for i, mid in enumerate(mod_list, 2):
        ws2.cell(i, 1, mid); ws2.cell(i, 2, mods.get(mid, ''))
    for i, kp in enumerate(kp_list, 2):
        ws2.cell(i, 3, kp)
    dv1 = DataValidation(type='list', formula1=f'=词表!$A$2:$A${len(mod_list)+1}', allow_blank=True)
    dv2 = DataValidation(type='list', formula1=f'=词表!$C$2:$C${len(kp_list)+1}', allow_blank=True)
    ws.add_data_validation(dv1); ws.add_data_validation(dv2)
    n = len(rows)
    dv1.add(f'R2:R{n+1}'); dv2.add(f'S2:S{n+1}')
    thin = Side(style='thin', color='BBBBBB'); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c in ws[1]:
        c.fill = PatternFill('solid', fgColor='DDEBF7'); c.font = Font(bold=True)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True); c.border = border
    widths = [6, 12, 24, 32, 24, 28, 8, 12, 90, 20, 20, 20, 24, 8, 50, 26, 20, 18, 22, 26, 48]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=True); c.border = border
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 70
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = f'A1:U{ws.max_row}'
    ws3 = wb.create_sheet('说明')
    if meta.get('full_census'):
        title_line = f"教材 {rule_l} 映射 · 剩余 {meta['model']} 块全量终检表"
        pool_line = f"reviewed 中 model {meta['model']} 块（teacher {meta['teacher']} 已排除）；全量入表，无抽样。"
        sample_line = f"全量 {meta['total']} 块，来源列统一为 `全量终检`。"
        pilot_line = None
        total_line = f"{meta['total']} 行。"
    elif meta['pilot']:
        title_line = f"教材 {rule_l} 映射 · 组合复核表（剩余 {meta['percent']:g}% + pilot {meta['pilot']} 回采）"
        pool_line = (f"reviewed 中 model {meta['model']} 块（teacher {meta['teacher']} 已排除）；"
                     f"其中 pilot 100 块单列回采。")
        sample_line = (f"抽样池 = model − pilot = {meta['sampled_pool']}；{meta['percent']:g}% = "
                       f"{meta['sample_target']} 块；稀有状态全量，其余按册/置信分层、章轮转。")
        pilot_line = f"pilot {meta['pilot']} 块全量加入（来源列标 `pilot100回采`）。"
        total_line = f"{meta['total']} 行 = {meta['sample_target']} 抽样 + {meta['pilot']} pilot。"
    else:
        title_line = f"教材 {rule_l} 映射 · 复核表（剩余 {meta['model']} 块抽 {meta['percent']:g}%）"
        pool_line = f"reviewed 中 model {meta['model']} 块（teacher {meta['teacher']} 已排除）。"
        sample_line = (f"{meta['percent']:g}% = {meta['sample_target']} 块；"
                       f"按册比例、置信分层、章轮转抽取。")
        pilot_line = None
        total_line = f"{meta['total']} 行。"
    lines = [
        [title_line],
        [''],
        ['目的', '验证当前映射规则在未复核 model 块上的质量；本表只给模型候选，教师判定请填 教师模块/教师考点/备注。'],
        ['池', pool_line],
        ['抽样', sample_line],
    ]
    if pilot_line:
        lines.append(['pilot 回采', pilot_line])
    lines += [
        ['合计', total_line],
        ['排序', '按 册 → 页码 → part → ordinal 排序；来源列可筛选。'],
        ['列说明', f'模型模块/模型primary/名称/secondary/置信/理由 = {rule_l} 候选；{rule_l}规则 = 修正层来源；'
                   f'{prev_l}模型primary = 上一版候选，便于对比。'],
        ['待填', '教师模块、教师考点、备注 三列留空；模块 17 项、考点 120 项下拉。'],
        ['回填', '填完放回 review_sheets/filled/，命名不变；解析后更新 reviewed/PG，再重投影 Obsidian 链接。'],
    ]
    for r in lines:
        ws3.append(r)
    ws3['A1'].font = Font(bold=True, size=14)
    ws3.column_dimensions['A'].width = 20; ws3.column_dimensions['B'].width = 120
    pathlib.Path(args.out_xlsx).parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out_xlsx)
    print(f'[xlsx] {args.out_xlsx}（{n} 行 = {meta["sample_target"]}+{meta["pilot"]}）')


def main(argv=None):
    ap = argparse.ArgumentParser(description='v5 组合复核表（剩余20% + pilot100）')
    ap.add_argument('--reviewed', default=str(OUT / 'mapped_1797_reviewed_v5.json'))
    ap.add_argument('--mapped', default=str(OUT / 'mapped_1797_v5.json'))
    ap.add_argument('--percent', type=float, default=20.0)
    ap.add_argument('--seed', type=int, default=20261107)
    ap.add_argument('--out-json', default=str(OUT / 'sample_review_v5_20pct_pilot100_2026-11-07.json'))
    ap.add_argument('--out-xlsx', default=str(ROOT / 'review_sheets' / 'samples' /
                                              '教材映射复核_v5_剩余20pct+pilot100_2026-11-07.xlsx'))
    ap.add_argument('--out-report', default=str(ROOT / 'docs' / 'textbook_sample_v5_2026-11-07.md'))
    ap.add_argument('--rule-label', default='v5', help='规则列前缀（如 v6）')
    ap.add_argument('--prev-label', default='v4', help='上一版模型列前缀（如 v5）')
    ap.add_argument('--prev-mapped', default=None, help='上一版映射 json（默认 mapped_1797_v4.json）')
    ap.add_argument('--full-census', action='store_true',
                    help='全部剩余 model 入表（终检），不做抽样、不采 pilot')
    args = ap.parse_args(argv)

    rows, meta = build(args)
    pathlib.Path(args.out_json).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    write_xlsx(rows, meta, args)
    rule_l = getattr(args, 'rule_label', 'v5')
    if meta.get('full_census'):
        title = f'教材 {rule_l} 全量终检（{meta["model"]} 块）'
        lines = [f'- model 池 **{meta["model"]}**（teacher {meta["teacher"]} 已排除）；本轮全量入表，无抽样；',
                 f'- 共 **{meta["total"]}** 行；全量终检，seed 不适用。', '',
                 '## 构成', '', '| 来源 | 行数 |', '| --- | ---: |',
                 f'| 全量终检 | {meta["total"]} |',
                 f'| **合计** | **{meta["total"]}** |', '']
    elif meta['pilot']:
        title = f'教材 {rule_l} 组合复核表（剩余 {meta["percent"]:g}% + pilot {meta["pilot"]}）'
        lines = [f'- model 池 **{meta["model"]}**（teacher {meta["teacher"]} 排除）；抽样池 **{meta["sampled_pool"]}**；',
                 f'- {meta["percent"]:g}% 抽样 **{meta["sample_target"]}** 块 + pilot 全量 **{meta["pilot"]}** 块 = **{meta["total"]}** 行；',
                 f'- seed={meta["seed"]}；抽样与 pilot **零重叠**、与 teacher 零重叠。', '',
                 '## 构成', '', '| 来源 | 行数 |', '| --- | ---: |',
                 f'| {meta["percent"]:g}% 抽样 | {meta["sample_target"]} |',
                 f'| pilot100 回采 | {meta["pilot"]} |',
                 f'| **合计** | **{meta["total"]}** |', '']
    else:
        title = f'教材 {rule_l} 复核表（剩余 {meta["model"]} 块抽 {meta["percent"]:g}%）'
        lines = [f'- model 池 **{meta["model"]}**（teacher {meta["teacher"]} 已排除）；',
                 f'- {meta["percent"]:g}% 抽样 = **{meta["sample_target"]}** 块；seed={meta["seed"]}；与 teacher 零重叠。', '',
                 '## 构成', '', '| 来源 | 行数 |', '| --- | ---: |',
                 f'| {meta["percent"]:g}% 抽样 | {meta["sample_target"]} |',
                 f'| **合计** | **{meta["total"]}** |', '']
    L = ['---', 'type: report', f'title: {title}', 'updated: 2026-11-07',
         'status: sample-pending-review', '---', '',
         f'# {title}', ''] + lines + [
         '按册：' + '、'.join(f'{k} {v}' for k, v in meta['by_book'].items()), '',
         '## 校验', '',
         f'- block_id 唯一 {len(meta["block_ids"])}；与 teacher 零重叠；',
         '- xlsx 按册/页排序、完整原文非空、教师列留空、17/120 下拉。', '',
         '---', '', f'> 产物：`{pathlib.Path(args.out_xlsx).name}`、`{pathlib.Path(args.out_json).name}`。', '']
    pathlib.Path(args.out_report).write_text('\n'.join(L), encoding='utf-8')
    print(f'[sample] total={meta["total"]} sample={meta["sample_target"]} pilot={meta["pilot"]} '
          f'by_book={meta["by_book"]}')
    print(f'报告：{args.out_report}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
