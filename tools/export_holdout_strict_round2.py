"""Export strict-candidate round 2 to an Excel review workbook."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.strict_candidates_round2.json'
OUT = ROOT / 'review_sheets/samples/教师问题holdout120_strict复核_round2_2026-11-07.xlsx'

FILL = PatternFill('solid', fgColor='1F4E78')
FONT = Font(color='FFFFFF', bold=True)
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical='top')


def main() -> int:
    doc = __import__('json').loads(DATA.read_text(encoding='utf-8'))
    wb = Workbook()
    ws0 = wb.active
    ws0.title = '说明'
    ws0.column_dimensions['A'].width = 20
    ws0.column_dimensions['B'].width = 100
    ws0['A1'] = 'holdout120 strict候选 round 2'
    ws0['A1'].font = Font(bold=True, size=14, color='1F4E78')
    items = [
        ('目的', '把 holdout strict 从 6 条扩到 20+；本表 18 条查询，候选来自 H 与 HR 各 top-5 的并集。'),
        ('怎么填', '每行候选若应作为 strict gold，在“教师选择√”列写“√”；一组查询可选 0–2 个 chunk（组合 gold）。'),
        ('没合适的', '全部留空，并在备注写“无合适候选/需重找”；不要硬选。'),
        ('注意', '先看 query 和 strict_plan；question 类优先题干块，definition/theorem/formula 优先教材正文块。'),
        ('后续', '回填后我在 holdout 数据集写 strict，跑 H/HR/路由 strict + CI。'),
    ]
    r = 2
    for label, text in items:
        ws0.cell(r, 1, label).font = Font(bold=True)
        ws0.cell(r, 2, text).alignment = WRAP
        ws0.row_dimensions[r].height = 34
        r += 1

    ws = wb.create_sheet('strict候选')
    columns = [('序号', 6), ('id', 18), ('query', 42), ('strict_plan', 12),
               ('候选', 6), ('来源模式', 10), ('排名', 6), ('chunk_id', 40),
               ('来源/位置', 28), ('摘录', 72), ('教师选择√', 10), ('备注', 24)]
    for c, (name, width) in enumerate(columns, 1):
        cell = ws.cell(1, c, name)
        cell.fill = FILL
        cell.font = FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = 'C2'
    row = 2
    for i, item in enumerate(doc['rows'], 1):
        for j, cand in enumerate(item['candidates'], 1):
            values = [i, item['id'], item['query'], item['strict_plan'], j,
                      cand.get('mode', ''), cand.get('rank', ''), cand['chunk_id'],
                      f"{cand['title']} {cand['locator']}", cand['excerpt'], '', '']
            for c, value in enumerate(values, 1):
                cell = ws.cell(row, c, value)
                cell.border = BORDER
                cell.alignment = WRAP
            ws.row_dimensions[row].height = 42
            row += 1
    ws.auto_filter.ref = f'A1:L{row - 1}'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f'wrote {OUT} queries={len(doc["rows"])} candidate_rows={row - 2}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
