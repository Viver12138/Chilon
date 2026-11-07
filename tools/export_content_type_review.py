"""Export the content_type draft review sample to a teacher-editable Excel.

Input:  var/textbook_mapping/textbook_content_type_review_sample.json
Output: review_sheets/samples/教材内容类型标注复核_2026-11-07.xlsx
"""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / 'var/textbook_mapping/textbook_content_type_review_sample.json'
OUT = ROOT / 'review_sheets/samples/教材内容类型标注复核_2026-11-07.xlsx'

TYPES = ['definition', 'theorem', 'formula', 'example', 'exercise', 'catalog', 'reading', 'other']
TYPE_CN = {
    'definition': '定义', 'theorem': '定理/性质', 'formula': '公式', 'example': '例题',
    'exercise': '练习/习题', 'catalog': '目录/小结', 'reading': '阅读/探究', 'other': '其他',
}
FILL = PatternFill('solid', fgColor='1F4E78')
FONT = Font(color='FFFFFF', bold=True)
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical='top')


def main() -> int:
    data = json.loads(INPUT.read_text(encoding='utf-8'))
    rows = data['rows']
    wb = Workbook()
    guide = wb.active
    guide.title = '说明'
    guide.column_dimensions['A'].width = 20
    guide.column_dimensions['B'].width = 100
    guide['A1'] = '教材块内容类型标注复核（v0 draft）'
    guide['A1'].font = Font(bold=True, size=14, color='1F4E78')
    items = [
        ('目的', '给 1797 个教师已复核教材块补 content_type（定义/定理/公式/例题/练习/目录/阅读/其他），用于检索按对象类型路由。'),
        ('本次样本', f"共 {len(rows)} 条，按 5 册分层抽样；不是全部 1797 条。"),
        ('怎么判', '看“摘录”：这条块在教材里主要承担什么角色，就选什么主类；如果同时含多种类型，在“补充标签”里写第二、第三类，用逗号分隔。'),
        ('主类优先级', '目录/小结 > 阅读/探究 > 练习/习题 > 例题 > 定义 > 定理/性质 > 公式 > 其他。一个块只选一个主类。'),
        ('注意', '“例1”块即使含定义，也优先标 example；章末“小结”块优先 catalog；纯例题解答不单独标 solution（教材块不拆解析）。'),
        ('输出', '教师确认后把文件放回 review_sheets/filled/，由管线转成 content_type v0 标注，再决定是否写入 PG。'),
        ('边界', 'rule-v0 自动预标有噪声（尤其 exercise/example/other），本次复核就是纠错；不要按检索结果反推标签。'),
    ]
    r = 2
    for label, value in items:
        guide.cell(r, 1, label).font = Font(bold=True)
        guide.cell(r, 2, value).alignment = WRAP
        guide.row_dimensions[r].height = 34
        r += 1

    ws = wb.create_sheet('复核表')
    columns = [('序号', 6), ('block_id', 20), ('教材', 24), ('页码', 8), ('摘录', 70),
               ('规则主类', 14), ('规则标签', 22), ('教师确认主类', 16), ('教师补充标签', 24), ('备注', 26)]
    for c, (name, width) in enumerate(columns, 1):
        cell = ws.cell(1, c, name)
        cell.fill = FILL
        cell.font = FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = 'C2'
    type_formula = '"' + ','.join(TYPES) + '"'
    for i, row in enumerate(rows, 2):
        values = [i - 1, row['block_id'], row['source_title'], row.get('page'), row.get('text_excerpt', ''),
                  row.get('primary'), '|'.join(row.get('labels') or []), '', '', '']
        for c, value in enumerate(values, 1):
            cell = ws.cell(i, c, value)
            cell.border = BORDER
            cell.alignment = WRAP
        ws.row_dimensions[i].height = 48
    last = 1 + len(rows)
    dv = DataValidation(type='list', formula1=type_formula, allow_blank=True, showDropDown=False)
    dv.error = '请选择 content_type'
    ws.add_data_validation(dv)
    dv.add(f'H2:H{last}')
    ws.auto_filter.ref = f'A1:J{last}'

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f'wrote {OUT} rows={len(rows)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
