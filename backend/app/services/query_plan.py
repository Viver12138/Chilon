"""QueryPlan v0: turn a teacher query into structured retrieval intent + hard filters.

This is the first P0 layer from the 2026-11-07 expert review.  It is deliberately
rule-based and conservative: only conditions the query states explicitly become
hard filters; everything else stays soft.  The JSON shape is the contract used by
`tools/eval_v2_qp.py` and, later, the product retrieval API.

Version: query-plan/v0.
"""

from __future__ import annotations

from typing import Any

from app.services import hybrid_retrieval as hr

PLAN_VERSION = "query-plan/v0"

QUESTION_VERBS = (
    "找一", "找两", "找二", "找三", "找四", "找五", "找几", "找一些", "找点",
    "出一", "出两", "出二", "出三", "出四", "出五", "出几",
    "来一", "来两", "来三", "来几",
    "给我", "有没有", "有哪些", "全部题目",
)
FORMULA_WORDS = ("公式", "表达式", "通项")
KNOWLEDGE_WORDS = ("定义", "定理", "性质", "概念", "内容", "适用条件", "判定", "法则", "几何意义")
ROLE_HINTS = {
    "压轴": "challenge",
    "基础": "basic",
    "中等": "medium",
    "易错": "error_prone",
    "综合": "comprehensive",
    "创新": "innovative",
}


def _contains_any(text: str, words: tuple[str, ...] | list[str]) -> bool:
    return any(word in text for word in words)


def build_plan(query: str) -> dict[str, Any]:
    """Build a v0 QueryPlan.  Deterministic; no model calls."""
    text = query.strip()
    base = hr.extract_conditions(text)

    formula = _contains_any(text, FORMULA_WORDS)
    knowledge = _contains_any(text, KNOWLEDGE_WORDS)
    asks_question = _contains_any(text, QUESTION_VERBS) and _contains_any(text, ("题", "卷", "真题", "模拟"))
    if not asks_question and _contains_any(text, ("真题", "模拟题")) and _contains_any(text, ("找", "来", "出", "给")):
        asks_question = True
    if not asks_question and "卷" in text and "题" in text:
        asks_question = True

    # Intent: explicit "formula/definition/theorem" beats a noun like 解答题;
    # an explicit request verb ("找一道…") means question search.
    if formula and not asks_question:
        intent = "formula_search"
    elif knowledge and not asks_question:
        intent = "knowledge_search"
    elif asks_question:
        intent = "question_search"
    else:
        intent = "mixed_search"

    if intent == "question_search":
        object_scope = "question"
    elif intent in ("formula_search", "knowledge_search"):
        object_scope = "knowledge"
    else:
        object_scope = "any"

    # Hard filters: only explicitly stated conditions.  Formula/knowledge
    # searches default to textbook because that is where 定义/定理/公式 live.
    hard: dict[str, Any] = {}
    if object_scope != "any":
        hard["question_scope"] = object_scope

    explicit_source = _contains_any(text, ("教材", "真题", "模拟卷", "模拟题", "高考真题"))
    if explicit_source and base.get("source_types"):
        hard["source_types"] = list(base["source_types"])
    elif object_scope == "knowledge":
        hard["source_types"] = ["textbook"]

    if base.get("year_range"):
        hard["year_range"] = list(base["year_range"])
    if base.get("papers") and intent in ("question_search", "mixed_search"):
        hard["papers"] = list(base["papers"])
    if object_scope == "question" and base.get("question_types"):
        hard["question_types"] = list(base["question_types"])

    role_hints = [label for word, label in ROLE_HINTS.items() if word in text]
    soft = {
        "knowledge_points": list(base.get("knowledge_points") or []),
        "keywords": list(base.get("keywords") or []),
        "role_hints": role_hints,
    }
    uncertain = []
    if intent == "mixed_search":
        uncertain.append("intent 无法唯一确定（可能是知识+题目混合检索）")
    if explicit_source and not base.get("source_types"):
        uncertain.append("提到了来源词但未能映射到 source_type")
    if role_hints and "difficulty" not in hard and "question_role" not in hard:
        uncertain.append("难度/题目定位只作为软标签（当前无 metadata 硬过滤）")

    return {
        "version": PLAN_VERSION,
        "query": text,
        "intent": intent,
        "object_scope": object_scope,
        "hard": hard,
        "soft": soft,
        "uncertain": uncertain,
        "extractor_conditions": {
            "year_range": base.get("year_range"),
            "source_types": base.get("source_types"),
            "papers": base.get("papers"),
            "question_types": base.get("question_types"),
        },
    }


def preferred_mode(plan: dict) -> str:
    """Interim H/HR routing from the 2026-11-07 decision memo.

    Default H (coverage); HR for explicit formula/definition/theorem lookups,
    including "A 和 B 有什么区别" comparison queries. Question/mixed list-style
    queries stay on H until per-category A/B says otherwise.
    """
    if plan.get("intent") in ("formula_search", "knowledge_search"):
        return "HR"
    if (plan.get("hard") or {}).get("question_scope") == "knowledge":
        return "HR"
    if plan.get("intent") == "mixed_search" and any(
        word in plan.get("query", "") for word in ("区别", "区分", "概念", "定义", "定理", "性质")
    ):
        return "HR"
    return "H"
