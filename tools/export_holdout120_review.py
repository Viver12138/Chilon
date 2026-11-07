"""Export the 120 holdout queries for teacher review of auto-extracted terms."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'corpus/eval/teacher_questions.holdout120.json'
STRICT = ROOT / 'corpus/eval/teacher_questions.holdout120.strict_candidates.json'
OUT = ROOT / 'review_sheets/samples/教师问题holdout120_期望词复核_2026-11-07.xlsx'

FILL = PatternFill('solid', fgColor='1F4E78')
FONT = Font(color='FFFFFF', bold=True)
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical='top')


def main() -> int:
    doc = __import__('json').loads(DATA.read_text(encoding='utf-8'))
    wb = Workbook()
    guide = wb.active
    guide.title = '说明'
    guide.column_dimensions['A'].width = 22
    guide.column_dimensions['B'].width = 95
    guide['A1'] = 'holdout120 期望词复核（draft）'
    guide['A1'].font = Font(bold=True, size=14, color='1F4E78')
    items = [
        ('目的', '120 条 holdout 教师问题未参与 v2 调参；本表复核“自动期望词”，复核后才能用于样本外评测。'),
        ('当前状态', '期望词由 qwen-plus 抽取；strict 尚未标注，所以本表只确认 lenient 检索词。'),
        ('怎么填', '在“教师修正期望词”列填 3–6 个检索词/短语，用中文分号或逗号分隔；若自动词可用，写“同意”或留空表示沿用。'),
        ('注意', '不要写“怎么求/有哪些/题目”等泛词；优先学科术语；不要按检索结果反推。'),
        ('strict', 'strict 金标需要单独候选复核；本表不替代 strict 标注。'),
        ('边界', '未复核前，holdout 只能做“预跑”，不能作为样本外结论。'),
    ]
    r = 2
    for label, text in items:
        guide.cell(r, 1, label).font = Font(bold=True)
        guide.cell(r, 2, text).alignment = WRAP
        guide.row_dimensions[r].height = 34
        r += 1

    ws = wb.create_sheet('复核表')
    columns = [('序号', 6), ('id', 18), ('类别', 14), ('来源', 30), ('query', 48),
               ('自动期望词', 40), ('教师修正期望词', 40), ('strict_plan', 12), ('备注', 24)]
    for c, (name, width) in enumerate(columns, 1):
        cell = ws.cell(1, c, name)
        cell.fill = FILL
        cell.font = FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = 'C2'
    for i, q in enumerate(doc['queries'], 2):
        values = [i - 1, q['id'], q['category'], q['source'], q['text'],
                  '、'.join(q.get('terms') or []), '', q.get('strict_plan') or '', '']
        for c, value in enumerate(values, 1):
            cell = ws.cell(i, c, value)
            cell.border = BORDER
            cell.alignment = WRAP
        ws.row_dimensions[i].height = 36
    ws.auto_filter.ref = f'A1:I{1 + len(doc["queries"])}'

    # Optional strict candidate sheet: 12 queries × top-5 H candidates.
    if STRICT.exists():
        strict = __import__('json').loads(STRICT.read_text(encoding='utf-8'))
        ws2 = wb.create_sheet('strict候选')
        cols = [('序号', 6), ('id', 18), ('query', 42), ('strict_plan', 12),
                ('候选', 6), ('chunk_id', 40), ('来源/位置', 30), ('摘录', 70), ('教师选择√', 10)]
        for c, (name, width) in enumerate(cols, 1):
            cell = ws2.cell(1, c, name)
            cell.fill = FILL
            cell.font = FONT
            cell.border = BORDER
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            ws2.column_dimensions[cell.column_letter].width = width
        ws2.freeze_panes = 'C2'
        r = 2
        for i, item in enumerate(strict['rows'], 1):
            for j, cand in enumerate(item['candidates'], 1):
                values = [i, item['id'], item['query'], item['strict_plan'], j,
                          cand['chunk_id'], f"{cand['title']} {cand['locator']}", cand['excerpt'], '']
                for c, value in enumerate(values, 1):
                    cell = ws2.cell(r, c, value)
                    cell.border = BORDER
                    cell.alignment = WRAP
                ws2.row_dimensions[r].height = 42
                r += 1
        ws2.auto_filter.ref = f'A1:I{r - 1}'

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f'wrote {OUT} rows={len(doc["queries"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
