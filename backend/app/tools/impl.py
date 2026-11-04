"""Concrete tool implementations.

Three tools cover the golden path:

* `knowledge.search` — real SQL over the platform knowledge base and the teacher's
  own uploads. Returns citations, not just text, because everything downstream must
  be able to point at a source.
* `content.generate` — DeepSeek when a key is configured, a deterministic stub
  otherwise. Both are validated by the same code, so the offline path proves the
  pipeline and the live path adds quality, not different rules.
* `quality.check` — structural and citation checks. It reports what it can prove and
  marks the rest "inconclusive"; it never claims a check it did not run.

Every tool returns a JSON-serialisable dict that is stored as the step's output.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import settings as config


class ToolFailed(Exception):
    """The tool ran but could not produce a usable result."""


@dataclass(frozen=True)
class ToolContext:
    owner_id: uuid.UUID
    execution_id: uuid.UUID
    step_key: str
    spec: dict[str, Any]
    requirement: dict[str, Any]
    deps: dict[str, Any]


# ── knowledge.search ────────────────────────────────────────────────────────────


async def knowledge_search(session: AsyncSession, ctx: ToolContext) -> dict[str, Any]:
    """Keyword retrieval over chunks, joined to their question when there is one.

    Retrieval stays keyword + metadata on purpose (embedding is deferred), so this
    is honest about being a first pass: it returns what it matched, with the
    locator, and lets the caller judge relevance.
    """
    requirement = ctx.requirement
    topic = (requirement.get("topic") or "").strip()
    sources = requirement.get("sources") or []
    limit = int(ctx.spec.get("limit") or 8)

    if not topic:
        raise ToolFailed("requirement has no topic to search for")

    params: dict[str, Any] = {"pattern": f"%{topic}%", "limit": limit}
    source_filter = ""
    if sources:
        source_filter = "AND s.source_type = ANY(:sources)"
        params["sources"] = sources

    rows = (
        await session.execute(
            text(
                f"""
                SELECT c.id AS chunk_id,
                       c.text_content,
                       c.locator,
                       q.id AS question_id,
                       q.question_no,
                       s.id AS source_id,
                       s.title,
                       s.source_type,
                       s.year,
                       dv.id AS document_version_id
                FROM knowledge_chunks c
                JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
                JOIN knowledge_sources s ON s.id = dv.source_id
                LEFT JOIN knowledge_questions q
                       ON q.document_version_id = dv.id
                      AND q.stem_locator = c.locator
                WHERE dv.lifecycle_status IN ('approved', 'indexed')
                  AND c.text_content ILIKE :pattern
                  {source_filter}
                ORDER BY s.source_type, c.ordinal
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()

    hits = [
        {
            "chunk_id": str(r.chunk_id),
            "question_id": str(r.question_id) if r.question_id else None,
            "question_no": r.question_no,
            "source_id": str(r.source_id),
            "source_title": r.title,
            "source_type": r.source_type,
            "year": r.year,
            "document_version_id": str(r.document_version_id),
            "locator": r.locator,
            "excerpt": (r.text_content or "")[:400],
        }
        for r in rows
    ]
    return {"topic": topic, "hit_count": len(hits), "hits": hits}


# ── content.generate ────────────────────────────────────────────────────────────


GENERATE_PROMPT = """你是高中数学命题助手。根据给定课题与参考资料，命制题目。

要求：
1. 只输出 JSON，不要 markdown 代码块。
2. 每题必须有题干、答案、简析，且题目可独立作答。
3. citation_chunk_id 必须取自给定参考资料的 chunk_id；没有可用资料时留空字符串。
4. 题目不得重复。

输出格式：
{"questions": [{"no": "1", "stem": "...", "answer": "...", "explanation": "...", "citation_chunk_id": "..."}]}"""


def _validate_questions(payload: Any, expected: int | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ToolFailed("generator did not return an object")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ToolFailed("generator returned no questions")

    cleaned: list[dict[str, Any]] = []
    stems: set[str] = set()
    for index, q in enumerate(questions, 1):
        if not isinstance(q, dict):
            raise ToolFailed(f"question #{index} is not an object")
        stem = str(q.get("stem") or "").strip()
        answer = str(q.get("answer") or "").strip()
        if not stem:
            raise ToolFailed(f"question #{index} has no stem")
        if not answer:
            # a question without an answer cannot be checked or put in the teacher version
            raise ToolFailed(f"question #{index} has no answer")
        digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()
        if digest in stems:
            raise ToolFailed(f"question #{index} duplicates an earlier one")
        stems.add(digest)
        cleaned.append(
            {
                "no": str(q.get("no") or index),
                "stem": stem,
                "answer": answer,
                "explanation": str(q.get("explanation") or "").strip(),
                "citation_chunk_id": str(q.get("citation_chunk_id") or "").strip() or None,
            }
        )

    if expected and abs(len(cleaned) - expected) > max(2, expected // 4):
        raise ToolFailed(f"asked for about {expected} questions, got {len(cleaned)}")
    return cleaned


def _stub_questions(topic: str, count: int, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic stand-in used when no API key is configured.

    It is obviously a stub — the stems say so — because a template pretending to be
    a generated question would be worse than an empty field.
    """
    out = []
    for i in range(1, count + 1):
        hit = hits[(i - 1) % len(hits)] if hits else None
        out.append(
            {
                "no": str(i),
                "stem": f"[模板占位] 关于「{topic}」的第 {i} 题：此处由生成器产出题干。",
                "answer": "（占位答案）",
                "explanation": "未接入模型时的占位内容，用于验证流水线。",
                "citation_chunk_id": hit["chunk_id"] if hit else None,
            }
        )
    return out


async def _call_deepseek(prompt_user: str) -> dict[str, Any]:
    s = config.load()
    if not s.llm_configured:
        raise ToolFailed("DeepSeek is not configured")
    url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": s.deepseek_model,
        "messages": [
            {"role": "system", "content": GENERATE_PROMPT},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.4,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=s.deepseek_timeout_seconds) as client:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {s.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if r.status_code != 200:
        raise ToolFailed(f"DeepSeek HTTP {r.status_code}: {r.text[:200]}")
    return json.loads(r.json()["choices"][0]["message"]["content"])


async def content_generate(session: AsyncSession, ctx: ToolContext) -> dict[str, Any]:
    requirement = ctx.requirement
    topic = (requirement.get("topic") or "").strip()
    count = int(requirement.get("question_count") or ctx.spec.get("count") or 5)

    # a generation step may run alongside siblings; it must only read its own branch
    search = next((v for v in ctx.deps.values() if v and "hits" in v), None)
    hits = search["hits"] if search else []

    engine = (ctx.spec.get("engine") or config.load().planner or "template").lower()
    use_model = engine != "template" and config.load().llm_configured

    if use_model:
        refs = "\n".join(
            f"- chunk_id={h['chunk_id']}：《{h['source_title']}》{(h.get('excerpt') or '')[:120]}"
            for h in hits[:6]
        ) or "（无可用参考资料）"
        prompt = f"课题：{topic}\n题量：{count}\n参考资料：\n{refs}\n\n请输出 JSON。"
        raw = await _call_deepseek(prompt)
        questions = _validate_questions(raw, count)
        generator = "deepseek"
    else:
        questions = _validate_questions({"questions": _stub_questions(topic, count, hits)}, count)
        generator = "template"

    return {"topic": topic, "count": len(questions), "generator": generator, "questions": questions}


# ── quality.check ───────────────────────────────────────────────────────────────


_ARITHMETIC = re.compile(r"(\d+)\s*([+\-*/])\s*(\d+)\s*=\s*(\d+)")


def _arithmetic_issues(text_value: str, where: str) -> list[dict[str, Any]]:
    """Checks the arithmetic that literally appears in the text.

    This is the only numeric check that can be done without a symbolic engine, and
    it is honest about its scope: it verifies stated equalities, not derivations.
    """
    issues = []
    for m in _ARITHMETIC.finditer(text_value):
        left, op, right, claimed = m.group(1), m.group(2), m.group(3), m.group(4)
        a, b, c = int(left), int(right), int(claimed)
        actual = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else None}[op]
        if actual is None or abs(actual - c) > 1e-9:
            issues.append(
                {
                    "code": "math.arithmetic",
                    "severity": "S1",
                    "message": f"{where}: {a} {op} {b} = {c}，实际为 {actual}",
                }
            )
    return issues


async def quality_check(session: AsyncSession, ctx: ToolContext) -> dict[str, Any]:
    generated = next((v for v in ctx.deps.values() if v and "questions" in v), None)
    if generated is None:
        raise ToolFailed("quality.check has no generated questions to check")

    search = next((v for v in ctx.deps.values() if v and "hits" in v), None)
    known_chunks = {h["chunk_id"] for h in (search["hits"] if search else [])}
    reportable_chunks = {h["chunk_id"] for h in (search["hits"] if search else [])}

    issues: list[dict[str, Any]] = []
    questions = generated["questions"]

    for q in questions:
        where = f"第 {q['no']} 题"
        if not q.get("answer"):
            issues.append({"code": "structure.no_answer", "severity": "S0", "message": f"{where} 缺答案"})

        chunk = q.get("citation_chunk_id")
        if chunk and chunk not in known_chunks:
            # a citation to something the search never returned is an invented source
            issues.append(
                {
                    "code": "citation.unresolved",
                    "severity": "S0",
                    "message": f"{where} 引用了检索结果之外的来源 {chunk}",
                }
            )
        if not chunk:
            issues.append(
                {
                    "code": "citation.missing",
                    "severity": "S3",
                    "message": f"{where} 未标注来源",
                }
            )

        for field in ("stem", "answer", "explanation"):
            issues.extend(_arithmetic_issues(q.get(field) or "", f"{where}.{field}"))

    unresolved = [i for i in issues if i["code"] == "citation.unresolved"]
    blocking = [i for i in issues if i["severity"] in ("S0", "S1")]

    return {
        "questions_checked": len(questions),
        "citations_available": len(reportable_chunks),
        "issues": issues,
        "blocking": len(blocking),
        "verdict": "blocked" if blocking else ("passed_with_warnings" if issues else "passed"),
        # what this check did NOT do, stated instead of implied
        "not_checked": [
            "符号推导（未接入符号引擎）",
            "数值样例验证",
            "解题步骤正确性",
            "跨材料一致性",
        ],
        "unresolved_citations": len(unresolved),
    }


TOOLS: dict[str, Callable[[AsyncSession, ToolContext], Awaitable[dict[str, Any]]]] = {
    "knowledge.search": knowledge_search,
    "content.generate": content_generate,
    "quality.check": quality_check,
}
