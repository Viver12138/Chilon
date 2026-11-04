"""Structural audit for the Chilon design documents.

Reports the layout properties that affect readability, review and renderer
compatibility. Fenced code, inline code, link targets and horizontal rules are
excluded from the content metrics so the numbers reflect what a reader sees.

Usage:
    python design/doc_audit.py
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / "Chilon_Project_Design_Master_Document.md",
    ROOT / "design" / "Chilon_Design_Volume_D1_Product_Closure_Protocol.md",
]

CJK = re.compile(r"[\u4e00-\u9fff]")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
CHECKBOX = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
PIPE_TABLE = re.compile(r"^\s*\|")
SIMPLE_TABLE = re.compile(r"^\s{2,}-{2,}(\s+-{2,})+\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
RULE = re.compile(r"^\s*-{3,}\s*$")
PROTECTED = re.compile(r"(`[^`]*`|\]\([^)]*\)|\]\(#[^)]*\))")
TERMINAL = "。！？；：」』）).!?:;"


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def audit(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    s: dict = {"path": path, "lines": len(lines), "chars": len(text)}
    headings: list[tuple[int, str]] = []
    in_fence = False
    pipe_rows = pipe_tables = simple_tables = 0
    prev_pipe = False
    wrapped = 0
    hard_breaks = trailing_ws = 0
    straight = curly = double_hyphen = 0
    rows_clean: list[int] = []

    for i, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = HEADING.match(line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip()))

        if SIMPLE_TABLE.match(line):
            simple_tables += 1

        if PIPE_TABLE.match(line):
            pipe_rows += 1
            if not prev_pipe:
                pipe_tables += 1
            prev_pipe = True
        else:
            prev_pipe = False

        if line.rstrip() != line:
            trailing_ws += 1
        if line.endswith("\\"):
            hard_breaks += 1

        clean = PROTECTED.sub("", line)
        if RULE.match(clean) or SIMPLE_TABLE.match(clean):
            continue
        straight += clean.count('"')
        curly += clean.count("“") + clean.count("”")
        double_hyphen += len(re.findall(r"\S--\S", clean))

        rows_clean.append(width(line))

        stripped = line.strip()
        prev = lines[i - 1].strip() if i else ""
        if (
            stripped
            and prev
            and not prev.endswith(tuple(TERMINAL))
            and not prev.endswith(("|", "\\"))
            and len(prev) > 20
            and CJK.match(stripped[0])
            and not HEADING.match(line)
        ):
            wrapped += 1

    checkboxes = [re.sub(r"\s+", "", m.group(1)) for m in map(CHECKBOX.match, lines) if m]

    s.update(
        {
            "headings": headings,
            "h1": sum(1 for d, _ in headings if d == 1),
            "h2": sum(1 for d, _ in headings if d == 2),
            "h3": sum(1 for d, _ in headings if d == 3),
            "h4": sum(1 for d, _ in headings if d >= 4),
            "max_depth": max((d for d, _ in headings), default=0),
            "has_toc": "toc:start" in text,
            "pipe_tables": pipe_tables,
            "pipe_rows": pipe_rows,
            "simple_tables": simple_tables,
            "wrapped": wrapped,
            "hard_breaks": hard_breaks,
            "trailing_ws": trailing_ws,
            "checkboxes": len(checkboxes),
            "dup_checkboxes": sum(1 for _t, c in Counter(checkboxes).items() if c > 1),
            "straight_quotes": straight,
            "curly_quotes": curly,
            "double_hyphen": double_hyphen,
            "links": len(re.findall(r"\]\([^)]*\)", text)),
            "prose_refs": len(re.findall(r"详见\s*\d+(\.\d+)+", text)),
            "widest": max(rows_clean) if rows_clean else 0,
            "over_100": sum(1 for w in rows_clean if w > 100),
        }
    )
    return s


def report(s: dict) -> None:
    print("=" * 76)
    print(s["path"].name)
    print("=" * 76)
    print(f"行数 {s['lines']}   字符 {s['chars']}   最宽可见列 {s['widest']}")
    print(f"标题 H1/H2/H3/H4+ = {s['h1']}/{s['h2']}/{s['h3']}/{s['h4']}   最大层级 {s['max_depth']}")
    print(f"目录: {'有' if s['has_toc'] else '无'}   链接 {s['links']} 处   未链接的散文引用 {s['prose_refs']} 处")
    print(f"表格: 竖线表 {s['pipe_tables']} 个 / {s['pipe_rows']} 行   遗留简单表 {s['simple_tables']} 个")
    print(f"折行: 句中断行 {s['wrapped']} 行   行尾反斜杠 {s['hard_breaks']} 处   行尾空白 {s['trailing_ws']} 行")
    print(f"宽度: 可见宽度 >100 的行 {s['over_100']} 行")
    print(f"清单: {s['checkboxes']} 条复选框（重复 {s['dup_checkboxes']} 组）")
    print(f"标点: 直引号 {s['straight_quotes']} / 弯引号 {s['curly_quotes']}   双连字符 {s['double_hyphen']} 处")
    print()


def main() -> int:
    for path in TARGETS:
        if not path.exists():
            print(f"SKIP {path}")
            continue
        report(audit(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
