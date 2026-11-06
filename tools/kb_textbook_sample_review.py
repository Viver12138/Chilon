#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材复核抽样（v4）：对剩余 model 块按比例抽复核样本并生成教师复核 xlsx。

口径（2026-11-06 v4）：
  - 池 = reviewed_v4 中 review_status=model 的块（不含 teacher 360 块）；
  - 目标 n = ceil(池大小 × percent%)；默认 20% → 1437 × 20% = 288；
  - 稀有状态做**全量采集**：vocab_gap 全部、non_content 全部（数量少、判定成本低）；
  - 其余预算给 mapped 块：按册 + 置信分层（≤0.70 / >0.70）比例分配，册内按章轮转抽取；
  - 映射阶段不读教师标签；抽样只读 v4 映射与 reviewed，不写 PG/vault/OCR。

阶段：
  --stage sample   抽样并写 sample json + 报告
  --stage xlsx     由 sample json + v4 映射生成教师复核 xlsx（需要 openpyxl）
  默认 --stage all 依次执行（系统 python 即可，本工具不连 DB）。

输出：
  var/textbook_mapping/sample_review_v4_20pct_2026-11-06.json
  var/textbook_mapping/sample_review_v4_20pct_2026-11-06.md
  review_sheets/samples/教材映射复核_v4_剩余1437块_20pct_2026-11-06.xlsx
  --include-pilot 时输出 `_inclpilot` 版本（xlsx 文件名含“含pilot”），两套互不覆盖。
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
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
REVIEWED = OUT / 'mapped_1797_reviewed_v4.json'
MAPPED_V4 = OUT / 'mapped_1797_v4.json'
MAPPED_V3 = OUT / 'mapped_1797.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
SEED = 20261106
BOOK_ORDER = ['必修第一册', '必修第二册', '选择性必修第一册', '选择性必修第二册', '选择性必修第三册']


def book_key(title: str) -> str:
    for suffix in sorted(BOOK_ORDER, key=len, reverse=True):
        if title.endswith(suffix):
            return suffix
    return title


def risk_of(x: dict) -> str:
    if x.get('status') == 'non_content':
        return 'non_content'
    if x.get('status') == 'vocab_gap':
        return 'vocab_gap'
    return 'low_conf' if (x.get('confidence') or 0) <= 0.70 else 'normal'


def pick_spread(pool: list, n: int, rng: random.Random, selected: set) -> list:
    """按章轮转抽 n 个，尽量覆盖章与册。"""
    by_ch = collections.defaultdict(list)
    for b in pool:
        if b['block_id'] in selected:
            continue
        by_ch[(book_key(b['book']), b.get('chapter_num') or 0, b.get('chapter') or '')].append(b)
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


def allocate(total: int, groups: dict, rng: random.Random) -> dict:
    """按组大小比例分配 total（最大余数法），每组不超过其大小。"""
    size_sum = sum(groups.values())
    if size_sum == 0 or total == 0:
        return {k: 0 for k in groups}
    raw = {k: total * v / size_sum for k, v in groups.items()}
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


def build_sample(percent: float, seed: int, include_pilot: bool = False):
    reviewed = json.loads(REVIEWED.read_text(encoding='utf-8'))['items']
    v4_items = json.loads(MAPPED_V4.read_text(encoding='utf-8'))['items']
    v4 = {x['block_id']: x for x in v4_items}
    by_chunk = {x['chunk_id']: x['block_id'] for x in v4_items}
    pilot_ids = {by_chunk[b['chunk_id']] for b in
                 json.loads((OUT / 'sample_100.json').read_text(encoding='utf-8'))['blocks']
                 if b['chunk_id'] in by_chunk}
    model = [x for x in reviewed if x.get('review_status') == 'model']
    teacher_ids = {x['block_id'] for x in reviewed if x.get('review_status') == 'teacher'}
    # 目标仍按 20% × 1437（沿用上一轮 360=1797×20% 的口径）；
    # 默认抽样池剔除 pilot 100（已复核过）；--include-pilot 时纳入
    target = math.ceil(len(model) * percent / 100.0)
    eligible = list(model) if include_pilot else [x for x in model if x['block_id'] not in pilot_ids]
    rng = random.Random(seed)

    gap = [x for x in eligible if x.get('status') == 'vocab_gap']
    non = [x for x in eligible if x.get('status') == 'non_content']
    mapped = [x for x in eligible if x.get('status') == 'mapped']
    rare = gap + non
    mapped_budget = max(0, target - len(rare))

    # mapped：按册分配 → 册内按置信分层 → 章轮转
    mapped_by_book = collections.defaultdict(list)
    for x in mapped:
        mapped_by_book[book_key(x['book'])].append(x)
    book_sizes = {b: len(mapped_by_book[b]) for b in mapped_by_book}
    book_alloc = allocate(mapped_budget, book_sizes, rng)
    chosen = []
    selected = {x['block_id'] for x in rare}
    for book in sorted(book_alloc, key=BOOK_ORDER.index):
        book_pool = [x for x in mapped_by_book[book] if x['block_id'] not in selected]
        low = [x for x in book_pool if (x.get('confidence') or 0) <= 0.70]
        normal = [x for x in book_pool if (x.get('confidence') or 0) > 0.70]
        n_book = min(book_alloc[book], len(book_pool))
        # 册内至少 1 个低置信（如果存在），其余按比例
        low_quota = 0
        if low and n_book > 0:
            low_quota = max(1, round(n_book * len(low) / len(book_pool)))
            low_quota = min(low_quota, len(low), n_book)
        normal_quota = n_book - low_quota
        take = pick_spread(low, low_quota, rng, selected)
        selected |= {x['block_id'] for x in take}
        take += pick_spread(normal, normal_quota, rng, selected)
        selected |= {x['block_id'] for x in take}
        # 分数/预算不足时用本册剩余块补
        need = n_book - len(take)
        if need > 0:
            rest = [x for x in book_pool if x['block_id'] not in selected]
            rng.shuffle(rest)
            take += rest[:need]
            selected |= {x['block_id'] for x in take}
        chosen += take
    # 总预算兜底（册分配舍入导致不足时，从 mapped 全池补）
    if len(rare) + len(chosen) < target:
        rest = [x for x in mapped if x['block_id'] not in selected]
        rng.shuffle(rest)
        need = target - len(rare) - len(chosen)
        chosen += rest[:need]
        selected |= {x['block_id'] for x in chosen}
    ids = [x['block_id'] for x in rare + chosen]
    if len(ids) != target or len(set(ids)) != target:
        raise SystemExit(f'样本数异常：{len(ids)}（目标 {target}）')
    if teacher_ids & set(ids):
        raise SystemExit('样本与 teacher 360 重叠')
    if not include_pilot and pilot_ids & set(ids):
        raise SystemExit('样本与 pilot 100 重叠')
    pilot_n = 0 if include_pilot else len(pilot_ids)
    pilot_in_sample = len(set(ids) & pilot_ids)
    return (reviewed, v4, target, gap, non, mapped, rare, chosen, ids,
            len(model), len(eligible), pilot_n, pilot_in_sample)


def resolve_paths(args):
    """按是否纳入 pilot 选择输出路径（两套表互不覆盖）。"""
    if getattr(args, 'include_pilot', False):
        return (OUT / 'sample_review_v4_20pct_inclpilot_2026-11-06.json',
                OUT / 'sample_review_v4_20pct_inclpilot_2026-11-06.md',
                ROOT / 'review_sheets' / 'samples' /
                '教材映射复核_v4_剩余1437块_20pct_含pilot_2026-11-06.xlsx')
    return (OUT / 'sample_review_v4_20pct_2026-11-06.json',
            OUT / 'sample_review_v4_20pct_2026-11-06.md',
            ROOT / 'review_sheets' / 'samples' /
            '教材映射复核_v4_剩余1437块_20pct_2026-11-06.xlsx')


def stage_sample(args):
    (reviewed, v4, target, gap, non, mapped, rare, chosen, ids,
     pool_model, pool_eligible, pilot_n, pilot_in_sample) = build_sample(
        args.percent, args.seed, getattr(args, 'include_pilot', False))
    sample_path, report_path, _xlsx_path = resolve_paths(args)
    include_pilot = bool(getattr(args, 'include_pilot', False))
    by_book = collections.Counter(book_key(x['book']) for x in [v for v in reviewed if v['block_id'] in set(ids)])
    risk = collections.Counter(risk_of(x) for x in reviewed if x['block_id'] in set(ids))
    rate = len(ids) / pool_eligible * 100 if pool_eligible else 0
    sample_path.write_text(json.dumps({
        'seed': args.seed, 'percent': args.percent, 'target': target,
        'pool_model': pool_model, 'exclude_teacher': 360,
        'include_pilot': include_pilot,
        'exclude_pilot': pilot_n, 'pool_eligible': pool_eligible,
        'pilot_in_sample': pilot_in_sample,
        'eligible_rate_pct': round(rate, 1),
        'method': ('rare-status census (vocab_gap+non_content) + mapped stratified by book/confidence, '
                   'chapter round-robin'),
        'risk': dict(risk), 'by_book': dict(by_book),
        'block_ids': ids,
    }, ensure_ascii=False, indent=1), encoding='utf-8')
    pool_desc = (f'teacher 360 已复核、从池中剔除；pilot 100 已纳入抽样池（本表含 **{pilot_in_sample}** 行 pilot 块，'
                 f'用于补回当年缺失的逐块标签）' if include_pilot else
                 'teacher 360 与 pilot 100 已复核过、均从抽样池剔除')
    overlap_desc = ('样本与 teacher 360 零重叠；pilot 块在池内，可能重复出现（re-collect）'
                    if include_pilot else '样本与 teacher 360、pilot 100 零重叠')
    L = ['---', 'type: report', f'title: 教材 v4 复核抽样（{args.percent:g}%，{target} 块）', 'updated: 2026-11-06',
         'status: sample-pending-review', '---', '',
         f'# 教材 v4 复核抽样（{args.percent:g}%）', '',
         f'> 目标 **{target}** 块 = 1437 个 model 块 × 20%（沿用上一轮 360=1797×20% 的口径）；'
         f'{pool_desc}，可抽池 **{pool_eligible}**'
         f'（实际抽样率 {rate:.1f}%）；seed={args.seed}；不写 PG/vault/OCR。', '',
         '## 1. 抽样口径', '',
         f'- 池：reviewed_v4 中 `review_status=model` 的 1437 块，teacher 360 排除；'
         f'{"pilot 100 纳入" if include_pilot else "pilot 100 剔除"}；',
         '- 全量采集稀有状态：`vocab_gap` 全部 + `non_content` 全部；',
         '- 其余预算给 `mapped`：先按册比例分配，册内按置信分层（≤0.70 / >0.70），再按章轮转；',
         f'- 映射阶段不读教师标签；{overlap_desc}。', '',
         '## 2. 样本构成', '',
         '| 层 | 样本数 | 可抽池 |', '| --- | ---: | ---: |',
         f'| vocab_gap | {len(gap)} | {len(gap)} |',
         f'| non_content | {len(non)} | {len(non)} |',
         f'| mapped（分层抽） | {len(chosen)} | {len(mapped)} |',
         f'| **合计** | **{target}** | **{len(gap) + len(non) + len(mapped)}** |', '',
         '### 按册', '', '| 册 | 样本 |', '| --- | ---: |']
    for book in BOOK_ORDER:
        L.append(f'| {book} | {by_book.get(book, 0)} |')
    L += ['', '### 按风险', '', '| 风险 | 样本 |', '| --- | ---: |']
    for k in ['low_conf', 'normal', 'vocab_gap', 'non_content']:
        L.append(f'| {k} | {risk.get(k, 0)} |')
    L += ['', '## 3. 校验', '',
          f'- 目标 **{target}**、实际 **{len(ids)}**、唯一 block_id **{len(set(ids))}**；',
          f'- {overlap_desc}；',
          '- 分册/风险构成见上；xlsx 每行完整原文非空、教师列留空、17/120 下拉。', '',
          '---', '',
          f'> 产物：`{sample_path.name}`、`{_xlsx_path.name}`。', '']
    report_path.write_text('\n'.join(L), encoding='utf-8')
    print(f'[sample] target={target} got={len(ids)} eligible={pool_eligible} ({rate:.1f}%) '
          f'pilot_in_sample={pilot_in_sample} risk={dict(risk)} by_book={dict(by_book)}')
    print(f'报告：{report_path}')
    return 0


def module_map():
    mods = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mid = m.group(2)
            mods[mid.split('_')[1]] = {'id': mid, 'name': re.split(r'（', m.group(1))[0].strip()}
    return mods


def stage_xlsx(args):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter
    reviewed = {x['block_id']: x for x in json.loads(REVIEWED.read_text(encoding='utf-8'))['items']}
    v4 = {x['block_id']: x for x in json.loads(MAPPED_V4.read_text(encoding='utf-8'))['items']}
    v3 = {x['block_id']: x for x in json.loads(MAPPED_V3.read_text(encoding='utf-8'))['items']}
    sample_path, _report_path, xlsx_path = resolve_paths(args)
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    ids = sample['block_ids']
    items = []
    for bid in ids:
        r = reviewed[bid]
        x = dict(r)
        x['rule'] = v4.get(bid, {}).get('rule', '')
        x['v3_primary'] = v3.get(bid, {}).get('kp_primary', '')
        items.append(x)
    # 排序：按册 → 页码 → part → ordinal，方便教师按册看
    def sort_key(x):
        return (BOOK_ORDER.index(book_key(x['book'])), x['page'], x.get('part') or 0, x.get('ordinal') or 0)
    items.sort(key=sort_key)
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
    wb = Workbook(); ws = wb.active; ws.title = '复核v4_20pct'
    headers = ['序号', 'block_id', '册', '章', '节', '页码', '块类型', '完整原文', '模型模块',
               '模型primary', '名称', '模型secondary', '置信', '理由', 'v4规则', 'v3模型primary',
               '教师模块', '教师考点', '备注', '来源PDF']
    ws.append(headers)
    for i, x in enumerate(items, 1):
        src = next((p for stem, p in pdfs.items() if x['book'] in stem), str(pdf_dir))
        ws.append([i, x['block_id'], x['book'], x.get('chapter', ''), x.get('section', ''), x['page'],
                   x['block_type'], None, x.get('module_id', ''), x['kp_primary'], x.get('kp_name', ''),
                   ' '.join(x.get('kp_secondary') or []), x['confidence'], x['reason'],
                   x.get('rule', ''), x.get('v3_primary', ''), '', '', '', src])
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
    n = len(items)
    dv1.add(f'Q2:Q{n+1}'); dv2.add(f'R2:R{n+1}')
    thin = Side(style='thin', color='BBBBBB'); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c in ws[1]:
        c.fill = PatternFill('solid', fgColor='DDEBF7'); c.font = Font(bold=True)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True); c.border = border
    widths = [6, 24, 32, 24, 28, 8, 12, 90, 20, 20, 20, 24, 8, 50, 26, 20, 18, 22, 26, 48]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=True); c.border = border
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 70
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = f'A1:T{ws.max_row}'
    # 说明 sheet
    ws3 = wb.create_sheet('说明')
    if sample.get('include_pilot'):
        pool_line = (f"池 = 1437 个 model 块（teacher 360 已复核、不在本表；pilot 100 **已纳入**抽样池，"
                     f"本表含 {sample.get('pilot_in_sample', 0)} 行 pilot 块，用于补回缺失标签）；"
                     f"目标 {sample['target']} 块 = 1437×20%；seed={sample['seed']}。")
        old_line = '与 teacher 360 块零重叠；pilot 块在池内，可能在表内重复出现（re-collect，正常填写）。'
    else:
        pool_line = (f"池 = 1437 个 model 块（teacher 360 已复核、不在本表；pilot 100 已复核过、也从池中剔除，"
                     f"可抽池 {sample['pool_eligible']}）；目标 {sample['target']} 块 = 1437×20%（实际抽样率 "
                     f"{sample['eligible_rate_pct']}%）；seed={sample['seed']}。")
        old_line = '与 teacher 360 块、pilot 100 块均零重叠；本表 block_id 全部是未复核过的块。'
    lines = [
        ['教材 v4 映射 · 剩余 1437 块 20% 教师复核表' + ('（含 pilot 回采）' if sample.get('include_pilot') else '')],
        [''],
        ['目的', '验证 v4 规则在未复核 model 块上的质量；本表只给模型候选，教师判定请填 教师模块/教师考点/备注。'],
        ['池与比例', pool_line],
        ['抽样口径', '稀有状态全量：vocab_gap 8 + non_content 23；其余预算给 mapped：按册分配、册内按置信分层、章轮转。'],
        ['与旧样本', old_line],
        ['排序', '按 册 → 页码 → part → ordinal 排序，方便按册连续审阅。'],
        ['列说明', '模型模块/模型primary/名称/secondary/置信/理由 = v4 候选；v4规则 = 修正层来源（v3_base/SEC/PRI/FILL 等）；v3模型primary = 上一版候选，便于对比。'],
        ['待填', '教师模块、教师考点、备注 三列留空；模块 17 项、考点 120 项下拉。'],
        ['回填', '填完放回 review_sheets/filled/，命名不变；解析后更新 reviewed/PG，再重投影 Obsidian 链接。'],
    ]
    for r in lines:
        ws3.append(r)
    ws3['A1'].font = Font(bold=True, size=14)
    ws3.column_dimensions['A'].width = 20; ws3.column_dimensions['B'].width = 120
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)
    copy_to = getattr(args, 'xlsx_copy', None)
    if copy_to:
        target = pathlib.Path(copy_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(xlsx_path, target)
        print(f'[xlsx] {xlsx_path}（{n} 行）；副本 {target}')
    else:
        print(f'[xlsx] {xlsx_path}（{n} 行）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材 v4 复核抽样（百分比）与出表')
    ap.add_argument('--stage', choices=['sample', 'xlsx', 'all'], default='all')
    ap.add_argument('--percent', type=float, default=20.0, help='抽样比例（相对 model 池，默认 20）')
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--include-pilot', action='store_true',
                    help='把 100 个 pilot 块纳入抽样池（补回缺失标签）；默认剔除')
    ap.add_argument('--xlsx-copy', default=os.environ.get('CHILON_XLSX_COPY'),
                    help='可选：把生成的复核 xlsx 复制到指定路径')
    args = ap.parse_args(argv)
    if args.stage in ('sample', 'all'):
        rc = stage_sample(args)
        if rc:
            return rc
    if args.stage in ('xlsx', 'all'):
        return stage_xlsx(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
