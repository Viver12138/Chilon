"""Derive 年份 and 卷别 from a source title.

The titles are the only place the information exists — the TeX corpus names a paper
`2024年新高考I卷`, the OCR corpus `2025年四川省绵阳三诊A卷`. Parsing them once into columns
is what makes "2024 新高考Ⅰ卷的解答题" retrievable at all; without it that query has no
word to match anywhere in the database.

Deterministic on purpose: a wrong year silently attached to 19 questions is worse than a
missing year.
"""

from __future__ import annotations

import re

YEAR = re.compile(r"(19|20)\d{2}")
#: the words that name a paper type; kept in the parsed value so it stays readable
PAPER_HINTS = (
    "新高考I卷", "新高考II卷", "新高考Ⅰ卷", "新高考Ⅱ卷", "新高考1卷", "新高考2卷",
    "新课标I卷", "新课标II卷", "新课标Ⅰ卷", "新课标Ⅱ卷", "新课标1卷", "新课标2卷",
    "全国甲卷", "全国乙卷", "全国丙卷", "全国I卷", "全国II卷", "全国III卷",
    "大纲卷", "上海卷", "北京卷", "天津卷", "江苏卷", "浙江卷", "山东卷",
    "安徽卷", "福建卷", "广东卷", "湖北卷", "湖南卷", "辽宁卷", "江西卷",
    "四川卷", "陕西卷", "重庆卷", "海南卷", "宁夏卷", "甘肃卷", "广西卷",
    "贵州卷", "云南卷", "河北卷", "河南卷", "山西卷", "内蒙古卷", "吉林卷",
    "黑龙江卷", "新疆卷", "西藏卷", "青海卷",
)
SESSIONS = ("春季", "春考", "春")


def parse_exam_meta(title: str | None) -> tuple[int | None, str | None]:
    """Return (year, paper). Either half may be None when the title does not say."""
    if not title:
        return None, None
    text = title.strip()

    year = None
    match = YEAR.search(text)
    if match:
        year = int(match.group(0))

    paper = None
    for hint in PAPER_HINTS:
        if hint in text:
            paper = hint
            break
    if paper is None and year is not None:
        # fall back to the title minus the year — only for titles that look like an exam;
        # a textbook title has no year and must stay without a paper name
        cleaned = YEAR.sub("", text)
        cleaned = re.sub(r"^[年\s（(]+|[)）\s]+$", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if cleaned:
            paper = cleaned[:64]

    for session in SESSIONS:
        if session in text and paper and "春" not in paper:
            paper = f"{paper}（{session}）"
            break
    return year, paper
