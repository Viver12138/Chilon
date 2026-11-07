"""Export the teacher-questions/v2 template to a teacher-fillable Excel + CSV.

The JSON template is the machine-readable source; this tool produces the
human-facing hand-off:

    python tools/export_teacher_questions_v2.py
    # -> review_sheets/samples/教师问题收集_v2.0_2026-11-07.xlsx
    # -> review_sheets/samples/教师问题收集_v2.0_2026-11-07.csv

The workbook has four sheets: 说明 / 填写表 / 示例 / strict金标说明.
Dropdowns cover category, intent, object type and strict object type; the 30
strict-planned slots are highlighted.  review_sheets/ is gitignored by design
(the filled file is the human hand-off archive, not a repo artifact).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = ROOT / "corpus" / "eval" / "teacher_questions.v2.template.json"
DEFAULT_XLSX = ROOT / "review_sheets" / "samples" / "教师问题收集_v2.0_2026-11-07.xlsx"
DEFAULT_CSV = ROOT / "review_sheets" / "samples" / "教师问题收集_v2.0_2026-11-07.csv"

CATEGORIES = ["主题词", "题型+知识点", "教材概念", "年份+卷别", "自然语言要求"]
INTENTS = ["find_topic", "find_question", "find_concept", "find_by_year", "find_by_type", "natural_language"]
OBJECT_TYPES = ["any", "question", "chunk", "knowledge_point"]
STRICT_TYPES = ["definition", "theorem", "formula", "question", "example", "section"]
YES_NO = ["是", "否"]

COLUMNS = [
    ("序号", 6),
    ("ID", 10),
    ("类别", 14),
    ("教师原话（逐字记录，不改写）", 46),
    ("教师匿名ID / 背景（如 T01/高三/教龄3年）", 26),
    ("收集日期", 12),
    ("意图", 16),
    ("对象类型", 14),
    ("expect.any（片段，分号分隔）", 30),
    ("strict 计划", 14),
    ("strict chunk_ids（UUID，分号分隔）", 40),
    ("strict object_type", 16),
    ("strict 理由", 30),
    ("核验人A", 10),
    ("核验人B", 10),
    ("expect 已核验", 14),
    ("strict 已核验", 14),
    ("备注", 26),
    ("填写提示", 55),
]

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
STRICT_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")


def add_title(ws, text: str, row: int = 1) -> int:
    ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=14, color="1F4E78")
    return row + 1


def build_instructions(wb: Workbook, data: dict) -> None:
    ws = wb.active
    ws.title = "说明"
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 100
    r = add_title(ws, "教师问题收集表 v2.0（Chilon 检索评测 · 中国区）")
    rows = [
        ("目的", "收集 2–3 位高中数学教师真实会提的检索需求；v2.0 目标 60 条，其中 30 条带 strict 金标。"),
        ("教师填写", "D 列写教师原话，逐字记录，不要改写；一条只表达一个检索意图；一句话多个要求请拆成多行。"),
        ("收集人填写", "E 列教师匿名ID/背景、F 列日期；不要写姓名/学校/联系方式。"),
        ("expect.any", "由核验人在冻结数据库里确认后的片段（分号分隔）；不是教师填写。"),
        ("strict 金标", "只对唯一确定对象填写：从 DB 导出 chunk_id，填 J–M 列；详见“strict金标说明”sheet。"),
        ("核验标记", "expect 已核验 / strict 已核验 选“是”才能进入数据集；strict 需两位核验人。"),
        ("类别配额", "主题词 12 / 题型+知识点 12 / 教材概念 12 / 年份+卷别 12 / 自然语言要求 12 = 60。"),
        ("strict 配额", "定义 8 / 定理 6 / 公式 6 / 完整题目 10 = 30；黄色底纹行是计划采集 strict 的槽位。"),
        ("冻结", "填完另存为 teacher_questions.v2.json 并跑校验；冻结后不再调参（调参用独立 dev 集）。"),
        ("校验命令", "python tools/check_teacher_questions_v2.py --input corpus/eval/teacher_questions.v2.json"),
        ("参考文档", "corpus/eval/V2_COLLECTION_GUIDE.md；schema: teacher_questions.v2.schema.json"),
    ]
    for label, value in rows:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=r, column=2, value=value)
        cell.alignment = WRAP
        ws.row_dimensions[r].height = 30
        r += 1
    r += 1
    r = add_title(ws, "本轮收集信息（请收集人填写）", r)
    meta = [
        ("收集人", ""),
        ("收集日期", ""),
        ("参与教师（匿名ID/年级/教龄段/是否用过AI）", ""),
        ("目标条数 / strict 目标", "60 / 30"),
        ("备注", ""),
    ]
    for label, value in meta:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=2, value=value).alignment = WRAP
        r += 1


def build_sheet(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("填写表")
    header_row = 1
    for index, (name, width) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=header_row, column=index, value=name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.row_dimensions[header_row].height = 42
    ws.freeze_panes = "D2"

    for offset, query in enumerate(data["queries"]):
        row = header_row + 1 + offset
        strict_plan = query.get("strict_plan") or ""
        values = [
            offset + 1,
            query["id"],
            query["category"],
            "",
            "",
            "",
            query.get("intent", ""),
            query.get("object_type", "any"),
            "",
            strict_plan,
            "",
            strict_plan,  # strict object_type 预填计划类型，实际可改
            "",
            "",
            "",
            "否",
            "否",
            "",
            query.get("fill_hint", ""),
        ]
        for index, value in enumerate(values, 1):
            cell = ws.cell(row=row, column=index, value=value)
            cell.alignment = WRAP
            cell.border = BORDER
            if index in (1, 2, 3, 7, 8, 10, 12, 16, 17):
                cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
            if strict_plan:
                cell.fill = STRICT_FILL
        ws.row_dimensions[row].height = 34

    last_row = header_row + len(data["queries"])
    validations = [
        (f"C2:C{last_row}", f'"{",".join(CATEGORIES)}"'),
        (f"G2:G{last_row}", f'"{",".join(INTENTS)}"'),
        (f"H2:H{last_row}", f'"{",".join(OBJECT_TYPES)}"'),
        (f"J2:J{last_row}", f'"{",".join(STRICT_TYPES)}"'),
        (f"L2:L{last_row}", f'"{",".join(STRICT_TYPES)}"'),
        (f"P2:P{last_row}", f'"{",".join(YES_NO)}"'),
        (f"Q2:Q{last_row}", f'"{",".join(YES_NO)}"'),
    ]
    for target, formula in validations:
        dv = DataValidation(type="list", formula1=formula, allow_blank=True, showDropDown=False)
        dv.error = "请选择下拉选项"
        dv.errorTitle = "值不在允许范围内"
        ws.add_data_validation(dv)
        dv.add(target)

    ws.auto_filter.ref = f"A{header_row}:S{last_row}"


def build_examples(wb: Workbook) -> None:
    ws = wb.create_sheet("示例")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 110
    r = add_title(ws, "填写示例（占位 UUID 不是真实数据）")
    examples = [
        ("定义（Q-C-01）", {
            "类别": "教材概念", "教师原话": "补集的定义是什么？",
            "对象类型": "chunk", "expect.any": "补集",
            "strict 计划": "definition",
            "strict chunk_ids": "00000000-0000-0000-0000-000000000001",
            "strict object_type": "definition",
            "strict 理由": "教材中补集定义的正文块；该定义只占一块。",
            "核验人A/B": "V01 / V02", "已核验": "是 / 是",
        }),
        ("定理（Q-C-09）", {
            "类别": "教材概念", "教师原话": "正弦定理的内容和适用条件？",
            "对象类型": "chunk", "expect.any": "正弦定理",
            "strict 计划": "theorem",
            "strict chunk_ids": "00000000-0000-0000-0000-000000000002",
            "strict object_type": "theorem",
            "strict 理由": "教材正弦定理所在块（含适用条件）。",
            "核验人A/B": "V01 / V02", "已核验": "是 / 是",
        }),
        ("题目（Q-B-03）", {
            "类别": "题型+知识点", "教师原话": "找一道 2024 新高考Ⅰ卷的圆锥曲线解答题",
            "对象类型": "question", "expect.any": "椭圆；离心率",
            "strict 计划": "question",
            "strict chunk_ids": "00000000-0000-0000-0000-000000000003",
            "strict object_type": "question",
            "strict 理由": "该题题干块；解析块默认不算 gold。",
            "核验人A/B": "V01 / V02", "已核验": "是 / 是",
        }),
    ]
    for title, fields in examples:
        r = add_title(ws, title, r)
        for key, value in fields.items():
            ws.cell(row=r, column=1, value=key).font = Font(bold=True)
            cell = ws.cell(row=r, column=2, value=value)
            cell.alignment = WRAP
            r += 1
        r += 1


def build_strict_help(wb: Workbook) -> None:
    ws = wb.create_sheet("strict金标说明")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 110
    r = add_title(ws, "strict 金标怎么填")
    items = [
        ("只有唯一对象才填", "某道原题、某条教材定义/定理/公式、某个知识点页；多目标/模糊需求只填 expect.any。"),
        ("chunk_ids 来源", "必须来自冻结数据库的 knowledge_chunks.id（UUID），不能用片段猜测或手写。"),
        ("SQL 示例", "SELECT c.id::text, left(c.text_content,80) FROM knowledge_chunks c "
                    "JOIN knowledge_document_versions dv ON dv.id=c.document_version_id "
                    "JOIN knowledge_sources s ON s.id=dv.source_id "
                    "WHERE s.title LIKE '%2024%' AND c.text_content LIKE '%题干片段%';"),
        ("多块对象", "一个对象被切成多块时，chunk_ids 填全部必要块（分号分隔）；Strict Recall@8 命中任意一块，Strict-all@8 要求全部入 top-8。"),
        ("题目 gold", "object_type=question 默认填题干块；解析/答案块不算 gold，除非标注明确说明必须包含。"),
        ("定义/定理/公式", "分别填教材定义、定理/性质、公式所在块；不要用例题块代替定义块。"),
        ("两位核验", "核验人A、B 独立确认 hit/no-hit 与 gold 正确性；strict 已核验选“是”前必须两人都确认。"),
        ("一致性", "目标 Cohen's κ ≥ 0.70；分歧由第三人裁决并记录。"),
        ("禁止", "不要用系统返回的结果反推 gold；不要按评测结果改 gold；不要只收系统答得对的题。"),
    ]
    for label, value in items:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=r, column=2, value=value)
        cell.alignment = WRAP
        ws.row_dimensions[r].height = 34
        r += 1


def write_csv(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([name for name, _ in COLUMNS])
        for offset, query in enumerate(data["queries"]):
            strict_plan = query.get("strict_plan") or ""
            writer.writerow([
                offset + 1,
                query["id"],
                query["category"],
                "",
                "",
                "",
                query.get("intent", ""),
                query.get("object_type", "any"),
                "",
                strict_plan,
                "",
                strict_plan,
                "",
                "",
                "",
                "否",
                "否",
                "",
                query.get("fill_hint", ""),
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Export teacher-questions/v2 to Excel + CSV")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--out-xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    data = json.loads(args.template.read_text(encoding="utf-8"))
    if data.get("version") != "teacher-questions/v2":
        print(f"不是 v2 模板：{data.get('version')}")
        return 2

    wb = Workbook()
    build_instructions(wb, data)
    build_sheet(wb, data)
    build_examples(wb)
    build_strict_help(wb)

    args.out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out_xlsx)
    write_csv(data, args.out_csv)
    print(f"xlsx: {args.out_xlsx}")
    print(f"csv : {args.out_csv}")
    print(f"rows: {len(data['queries'])}; strict planned: {sum(1 for q in data['queries'] if q.get('strict_plan'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
