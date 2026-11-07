"""Export the v2 draft strict-gold review sheet (Excel + CSV).

Reads the draft dataset and its gold-detail JSON; produces a teacher/annotator
review workbook (one row per gold chunk) with 通过/修改/不通过 dropdowns.

    python tools/export_v2_gold_review.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / 'corpus' / 'eval' / 'teacher_questions.v2.draft.json'
GOLD = ROOT / 'corpus' / 'eval' / 'teacher_questions.v2.draft.gold.json'
OUT_XLSX = ROOT / 'review_sheets' / 'samples' / '教师问题v2_strict金标核验_2026-11-07.xlsx'
OUT_CSV = ROOT / 'review_sheets' / 'samples' / '教师问题v2_strict金标核验_2026-11-07.csv'

COLUMNS = [
    ('序号', 6), ('查询ID', 10), ('类别', 12), ('教师原话', 38), ('strict 类型', 12),
    ('金标序号', 8), ('chunk_id', 40), ('来源', 22), ('位置', 22),
    ('摘录（前 600 字）', 60), ('为什么是 gold', 34),
    ('核验人A 结论', 14), ('核验人B 结论', 14), ('备注', 28),
]
HEADER_FILL = PatternFill('solid', fgColor='1F4E78')
HEADER_FONT = Font(color='FFFFFF', bold=True, size=10)
STRICT_FILL = PatternFill('solid', fgColor='FFF2CC')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical='top')


def main() -> int:
    draft = json.loads(DRAFT.read_text(encoding='utf-8'))
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    rows = gold['rows']

    wb = Workbook()
    guide = wb.active
    guide.title = '说明'
    guide.column_dimensions['A'].width = 20
    guide.column_dimensions['B'].width = 110
    guide['A1'] = 'v2.0 strict 金标核验表（draft）'
    guide['A1'].font = Font(bold=True, size=14, color='1F4E78')
    items = [
        ('用途', '两位核验人独立判断每条 strict 金标是否就是教师原话所指的 exact object；通过后才把 draft 的 strict_verified 置 true。'),
        ('现状', f"60 条问题来自问题收集1.txt（T01/T02/T03）；{gold['query_count']} 条 strict，{gold['chunk_rows']} 个 gold chunk；全部为 AI/SQL 候选，不是冻结基线。"),
        ('判定标准', 'chunk 必须来自冻结 DB 快照；object_type 正确（定义/定理/公式）；题目 gold 只算题干块；多块对象要能完整回答问题。'),
        ('怎么判', 'A/B 各自独立看“摘录 + rationale”，在“核验人A/B 结论”选“通过/修改/不通过”；修改需写清应换成哪个 chunk_id。'),
        ('一致性', '目标 Cohen’s κ ≥ 0.70；分歧由第三人裁决并记录。'),
        ('通过后', '两位都通过 → strict_verified=true；把 draft 另存为 teacher_questions.v2.json 并跑 checker（不带 --allow-unverified）。'),
        ('禁止', '不要按检索结果反推 gold；不要为了凑数把模糊查询标 strict；不要只收系统答得对的题。'),
        ('已知偏差', 'draft 的 strict 类型为定义 9 / 定理 6 / 公式 5（无题目类）；B01 焦点弦长无独立教材公式块，strict=null；B02 以导数几何意义段为 canonical。'),
    ]
    r = 2
    for label, value in items:
        guide.cell(r, 1, label).font = Font(bold=True)
        guide.cell(r, 2, value).alignment = WRAP
        guide.row_dimensions[r].height = 40
        r += 1

    ws = wb.create_sheet('核验表')
    for c, (name, width) in enumerate(COLUMNS, 1):
        cell = ws.cell(1, c, name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
        cell.border = BORDER
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 34
    ws.freeze_panes = 'C2'

    for i, row in enumerate(rows, 2):
        values = [
            i - 1,
            row['query_id'],
            row['category'],
            row['text'],
            row['object_type'],
            row['gold_index'],
            row['chunk_id'],
            row['title'],
            row['locator'],
            row['excerpt'],
            row['rationale'],
            '',
            '',
            '',
        ]
        for c, value in enumerate(values, 1):
            cell = ws.cell(i, c, value)
            cell.alignment = WRAP
            cell.border = BORDER
            cell.fill = STRICT_FILL
        ws.row_dimensions[i].height = 56

    last = 1 + len(rows)
    dv = DataValidation(type='list', formula1='"通过,修改,不通过"', allow_blank=True, showDropDown=False)
    dv.error = '请选择 通过/修改/不通过'
    ws.add_data_validation(dv)
    dv.add(f'L2:M{last}')
    ws.auto_filter.ref = f'A1:N{last}'

    wb.save(OUT_XLSX)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow([name for name, _ in COLUMNS])
        for i, row in enumerate(rows, 1):
            writer.writerow([
                i, row['query_id'], row['category'], row['text'], row['object_type'],
                row['gold_index'], row['chunk_id'], row['title'], row['locator'],
                row['excerpt'], row['rationale'], '', '', '',
            ])
    print(f'xlsx: {OUT_XLSX}')
    print(f'csv : {OUT_CSV}')
    print(f'queries={gold["query_count"]} chunk_rows={len(rows)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
