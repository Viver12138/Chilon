"""A starter knowledge-point taxonomy for Chinese high-school mathematics.

**This is authored curriculum data, and it is incomplete.** It covers the topics a
Gaokao paper spends most of its marks on, at the granularity a teacher would use to
ask for "a set of 三角函数 questions". It is not the national syllabus, and it is
versioned (`TAXONOMY_VERSION`) precisely because it will need replacing: a real
deployment should swap in a reviewed taxonomy without touching the parser.

Two rules keep it honest:

* **no default point.** Text that matches nothing returns an empty list. Tagging every
  question with something would make the tag useless for filtering — the whole value is
  that a tag means "this is what the question is about".
* **keywords are evidence, not intent.** `sin(2x)` is evidence for 三角函数. A question
  that merely mentions "函数" in passing may be mis-tagged, which is why the tag is
  stored as an array with a version, not as a single authoritative label.
"""

from __future__ import annotations

TAXONOMY_VERSION = "cn-gaokao-math-starter-1"

# Ordered: earlier rules win when several match, because the more specific a topic is,
# the earlier a teacher would expect it. 三角恒等变换 must precede 三角函数, otherwise
# every identity question is also tagged 三角函数 and the two become indistinguishable.
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("三角恒等变换", ("恒等变换", "两角和", "两角差", "二倍角", "辅助角", "降幂", "sin²", "cos²", "倍角")),
    ("解三角形", ("解三角形", "正弦定理", "余弦定理", "△abc", "勾股定理", "三角形", "内角")),
    ("三角函数", ("三角函数", "sin", "cos", "tan", "正弦", "余弦", "正切", "最小正周期", "周期", "相位", "振幅")),
    ("导数及其应用", ("导数", "切线", "极值", "单调递增区间", "单调递减区间", "最值", "f'(x)")),
    ("数列", ("数列", "等差", "等比", "通项", "前n项和", "递推")),
    ("平面向量", ("向量", "数量积", "共线", "坐标表示")),
    ("立体几何", ("棱柱", "棱锥", "球", "二面角", "线面", "体积", "表面积", "三视图")),
    ("解析几何", ("椭圆", "双曲线", "抛物线", "离心率", "焦点", "准线", "圆心")),
    ("概率与统计", ("概率", "期望", "方差", "分布", "抽样", "回归", "独立")),
    ("计数原理", ("排列", "组合", "二项式", "计数", "古典概型")),
    ("不等式", ("不等式", "均值不等式", "解集")),
    ("函数", ("函数", "定义域", "值域", "奇偶性", "对称轴")),
    ("复数", ("复数", "虚部", "实部", "共轭")),
    ("集合与逻辑", ("集合", "交集", "并集", "补集", "充分条件", "必要条件", "命题")),
)

MAX_POINTS = 4

# A more specific point makes the broader ones noise. A trigonometric question that
# asks for 单调递增区间 is not a 导数 question, even though the phrase also appears in
# derivative exercises; keeping both would make "give me derivative questions" return
# trigonometry.
SUPPRESSED_BY: dict[str, tuple[str, ...]] = {
    "三角函数": ("导数及其应用", "函数"),
    "三角恒等变换": ("导数及其应用", "函数"),
    "解三角形": ("三角函数", "函数"),
}


def tag(text: str) -> list[str]:
    """Return the knowledge points the text is evidence for, most specific first."""
    if not text:
        return []
    haystack = text.lower()
    found: list[str] = []
    for point, keywords in RULES:
        if point in found:
            continue
        if any(keyword in haystack for keyword in keywords):
            found.append(point)
        if len(found) >= MAX_POINTS + 2:
            break

    for point in list(found):
        for broader in SUPPRESSED_BY.get(point, ()):
            if broader in found:
                found.remove(broader)
    return found[:MAX_POINTS]


def points_of(text: str) -> list[str]:
    """Alias kept for readability at call sites that read like prose."""
    return tag(text)
