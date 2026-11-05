"""Exam metadata parsing: year and paper name, derived from the title only.

The columns exist because a teacher asks "2024 新高考Ⅰ卷的解答题" and that string appears
nowhere in the corpus. Parsing it at import time is what makes the question answerable —
and a wrong year attached to 19 questions is worse than no year, so the parser refuses to
guess where the title does not say.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.exam_meta import parse_exam_meta  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


CASES = [
    ("2012年安徽卷（理）", 2012, "安徽卷"),
    ("2024年新高考I卷", 2024, "新高考I卷"),
    ("2013年新课标II卷（文）", 2013, "新课标II卷"),
    ("2016年上海卷（春）", 2016, "上海卷（春）"),
]


def main() -> int:
    print("1. exam papers yield a year and a paper name")
    for title, year, paper in CASES:
        got_year, got_paper = parse_exam_meta(title)
        check(got_year == year, f"{title}: year {got_year} == {year}")
        check(got_paper == paper, f"{title}: paper {got_paper!r} == {paper!r}")

    print("2. a mock paper keeps its full name as the paper")
    year, paper = parse_exam_meta("2025年四川省绵阳三诊A卷")
    check(year == 2025, f"year 2025 (got {year})")
    check(paper is not None and "绵阳三诊" in paper, f"paper names the exam (got {paper!r})")

    print("3. a textbook has no year and no paper")
    year, paper = parse_exam_meta("普通高中教科书·数学（A版）必修第一册")
    check(year is None, f"no year (got {year})")
    check(paper is None, f"no paper (got {paper!r})")

    print("4. an empty or odd title does not invent a year")
    check(parse_exam_meta("") == (None, None), "empty title")
    check(parse_exam_meta(None) == (None, None), "None title")
    year, _ = parse_exam_meta("有些卷子原标题就没有年份")
    check(year is None, f"no year invented (got {year})")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: exam metadata is derived from titles without guessing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
