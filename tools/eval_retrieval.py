r"""Chilon 检索质量评测：问题集 x 真实知识库 x 固定判定口径。

口径与收集工装见 ``corpus/eval/README_retrieval.md``。本文件只做三件事：
读问题集、按同一口径判定命中、输出 JSON + Markdown 报告。

为什么默认只评 ``origin == "teacher"``：
    旧 ``corpus/eval/queries.json`` 是开发者自拟措辞（D.83 已承认不可信），
    ``teacher_questions.candidates.json`` 是 Agent 拟的模拟候选。它们可以演练工装
    或做 A/B 对照，但不能被当作"真实教师检索质量基线"。所以默认把它们排除；
    只有显式 ``--include-untrusted`` 才纳入，而且报告会写
    ``trustworthy_baseline = false`` 并列出原因，避免这些数字被误引用。

用法（完整说明见 README_retrieval.md）：

    python tools/eval_retrieval.py --selftest
    python tools/eval_retrieval.py --check-input --input corpus/eval/teacher_questions.json
    .\.venv\Scripts\python.exe tools/eval_retrieval.py --input corpus/eval/teacher_questions.json

退出码：
    0  完成（或自测 / 问题集校验通过）
    1  自测失败（指标逻辑有问题，先修脚本）
    2  无法评测：未配置 CHILON_TEST_DATABASE_URL
    3  无法评测：问题集缺失 / 不合法 / 没有可判定样本
    4  无法评测：缺少 Python 依赖（需要用 .venv 里的解释器）
    5  无法评测：数据库不可达或查询失败
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "corpus" / "eval"
DEFAULT_INPUT = EVAL_DIR / "teacher_questions.json"
LEGACY_INPUT = EVAL_DIR / "queries.json"
TEMPLATE_INPUT = EVAL_DIR / "teacher_questions.template.json"
CANDIDATES_INPUT = EVAL_DIR / "teacher_questions.candidates.json"
DEFAULT_OUT_PREFIX = ROOT / "var" / "retrieval" / "latest"

CATEGORIES = ("主题词", "题型+知识点", "教材概念", "年份+卷别", "自然语言要求")
ORIGINS = ("teacher", "simulated_candidate", "legacy_developer")
ORIGIN_LABELS = {
    "teacher": "真人教师",
    "simulated_candidate": "模拟候选",
    "legacy_developer": "旧自拟",
}
FIELDS = (
    "text", "excerpt", "title", "knowledge_points", "year", "paper", "source_type", "question_type"
)
OBJECT_TYPES = ("any", "chunk", "question", "paragraph")
# 数据集里 object_type 只是"这条问题想要什么对象"的标注，用于覆盖率统计；
# 判定规则由 expect 子句的 object 字段决定，两者是分开的。
QUERY_OBJECT_TYPES = ("any", "question", "chunk", "knowledge_point")

EXIT_OK = 0
EXIT_SELFTEST_FAILED = 1
EXIT_NO_DB = 2
EXIT_NO_DATA = 3
EXIT_NO_DEPS = 4
EXIT_DB_FAILED = 5

ENV_VAR = "CHILON_TEST_DATABASE_URL"
ENV_EXAMPLE = (
    "postgresql+psycopg://postgres:chilon_test_only@localhost:5432/chilon"
)


class DatasetError(Exception):
    """The question set cannot be loaded or understood."""


# ── small helpers ───────────────────────────────────────────────────────────────


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit() -> str | None:
    """Read HEAD without spawning git (works in worktrees too where .git is a file)."""
    try:
        git = ROOT / ".git"
        if git.is_file():
            return None
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref_path = git / head[5:]
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        return head[:12]
    except OSError:
        return None


def _mask_url(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]*@", r"\1***@", url)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _md_cell(text: object, limit: int = 32) -> str:
    value = str(text or "").replace("\n", " ").replace("|", "\\|")
    return value if len(value) <= limit else value[: limit - 1] + "…"


# ── dataset: load / normalize / validate ────────────────────────────────────────


def _normalize_clause(raw: object, qid: str) -> dict:
    """A clause is either a bare string (legacy shorthand) or a dict.

    simple dict keys:
        field    text | excerpt | title | knowledge_points | year | paper | source_type
        contains substring match (case-sensitive, verbatim)
        equals   exact match (for year/paper/source_type; knowledge_points membership)
        object   any | chunk | question | paragraph — hit object constraint
    group dict:
        all      list of clauses that must all match (AND); used for 年份+卷别 这类
                 需要同时约束 year 与 paper 的期望。any 数组本身仍是 OR。
    """
    if isinstance(raw, str):
        raw = {"field": "text", "contains": raw}
    if not isinstance(raw, dict):
        raise DatasetError(f"{qid}：expect 子句必须是字符串或对象，收到 {type(raw).__name__}")
    if "all" in raw:
        group = raw["all"]
        if not isinstance(group, list) or len(group) < 2:
            raise DatasetError(f"{qid}：expect 子句 all 必须是至少 2 条的数组")
        clause = {"all": [_normalize_clause(item, qid) for item in group]}
        if raw.get("note"):
            clause["note"] = str(raw["note"])
        return clause
    field = raw.get("field", "text")
    if field not in FIELDS:
        raise DatasetError(f"{qid}：expect 子句 field={field!r} 不合法，可选 {list(FIELDS)}")
    if ("contains" in raw) == ("equals" in raw):
        raise DatasetError(f"{qid}：expect 子句的 contains 与 equals 必须二选一")
    object_type = raw.get("object", "any")
    if object_type not in OBJECT_TYPES:
        raise DatasetError(f"{qid}：expect 子句 object={object_type!r} 不合法，可选 {list(OBJECT_TYPES)}")
    clause: dict = {"field": field, "object": object_type}
    for key in ("contains", "equals"):
        if key in raw:
            clause[key] = str(raw[key])
    if raw.get("note"):
        clause["note"] = str(raw["note"])
    return clause


def _normalize_query(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        raise DatasetError(f"queries[{index}] 不是对象")
    qid = str(raw.get("id") or "").strip() or f"Q{index + 1:02d}"
    category = raw.get("category")
    if category not in CATEGORIES:
        raise DatasetError(f"{qid}：category={category!r} 不合法，可选 {list(CATEGORIES)}")
    text = str(raw.get("text") or "").strip()
    legacy = "expect_any" in raw or "target" in raw
    if legacy and "expect" in raw:
        raise DatasetError(f"{qid}：旧字段（expect_any/target）与 expect 不能同时出现")

    origin = raw.get("origin")
    if origin is None:
        origin = "legacy_developer" if legacy else "teacher"
    if origin not in ORIGINS:
        raise DatasetError(f"{qid}：origin={origin!r} 不合法，可选 {list(ORIGINS)}")

    any_clauses: list[dict] = []
    strict: dict | None = None
    if legacy:
        raw_any = raw.get("expect_any") or []
        if not isinstance(raw_any, list):
            raise DatasetError(f"{qid}：expect_any 必须是数组")
        any_clauses = [_normalize_clause(item, qid) for item in raw_any]
        if raw.get("target"):
            strict = _normalize_clause({"field": "text", "contains": str(raw["target"])}, qid)
    else:
        expect = raw.get("expect") or {}
        if not isinstance(expect, dict):
            raise DatasetError(f"{qid}：expect 必须是对象")
        raw_any = expect.get("any") or []
        if not isinstance(raw_any, list):
            raise DatasetError(f"{qid}：expect.any 必须是数组")
        any_clauses = [_normalize_clause(item, qid) for item in raw_any]
        if expect.get("strict"):
            strict = _normalize_clause(expect["strict"], qid)

    object_type = str(raw.get("object_type") or "")
    if object_type and object_type not in QUERY_OBJECT_TYPES:
        raise DatasetError(
            f"{qid}：object_type={object_type!r} 不合法，可选 {list(QUERY_OBJECT_TYPES)}"
        )

    return {
        "id": qid,
        "category": category,
        "text": text,
        "origin": origin,
        "contributor": str(raw.get("contributor") or ""),
        "collected_at": str(raw.get("collected_at") or ""),
        "object_type": object_type,
        "expect_any": any_clauses,
        "strict": strict,
        "expect_verified": bool(raw.get("expect_verified", False)),
        "notes": str(raw.get("notes") or ""),
        "legacy": legacy,
    }


def load_dataset(path: Path) -> dict:
    if not path.exists():
        raise DatasetError(f"问题集不存在：{_rel(path)}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"问题集不是合法 JSON：{_rel(path)}（{exc}）") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("queries"), list):
        raise DatasetError(f"问题集顶层必须是对象且含 queries 数组：{_rel(path)}")

    entries = raw["queries"]
    legacy = bool(entries) and all(isinstance(item, dict) and "expect_any" in item for item in entries)
    provenance = raw.get("provenance") or {}
    if not isinstance(provenance, dict):
        raise DatasetError("provenance 必须是对象")
    if "status" not in provenance:
        if legacy:
            provenance["status"] = "developer_authored_legacy"
        else:
            simulated = any(isinstance(item, dict) and item.get("origin") == "simulated_candidate" for item in entries)
            provenance["status"] = "simulated" if simulated else "unknown"

    return {
        "path": path,
        "path_label": _rel(path),
        "sha256": _sha256(path),
        "version": str(raw.get("version") or ("legacy/queries.json" if legacy else "unknown")),
        "note": str(raw.get("note") or ""),
        "template": bool(raw.get("template", False)),
        "provenance": provenance,
        "legacy": legacy,
        "queries": [_normalize_query(item, index) for index, item in enumerate(entries)],
    }


def validate_dataset(dataset: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    queries = dataset["queries"]

    if not queries:
        errors.append("queries 为空：没有任何问题")

    seen: set[str] = set()
    by_category: Counter = Counter()
    by_origin: Counter = Counter()
    for query in queries:
        if query["id"] in seen:
            errors.append(f"{query['id']}：id 重复")
        seen.add(query["id"])
        by_category[query["category"]] += 1
        by_origin[query["origin"]] += 1

        if not query["text"]:
            errors.append(f"{query['id']}：text 为空（空白模板位未填写？）")
        if not query["expect_any"]:
            warnings.append(
                f"{query['id']}：expect.any 为空，不可判定——需先在语料里 SQL 核验对象后再填"
            )
        if query["strict"] and not query["expect_any"]:
            warnings.append(f"{query['id']}：只有 strict、没有 expect.any，strict 口径需要 lenient 作对照")
        if query["origin"] == "teacher":
            if not query["contributor"]:
                warnings.append(f"{query['id']}：origin=teacher 但缺 contributor（教师背景）")
            if not query["collected_at"]:
                warnings.append(f"{query['id']}：origin=teacher 但缺 collected_at（收集日期）")
        if query["origin"] == "simulated_candidate" and not query["notes"]:
            errors.append(f"{query['id']}：模拟候选必须写 notes，说明未经真人确认")

    if dataset["template"]:
        warnings.append("这是空白收集模板：text 未填写，不能运行评测")
    if dataset["legacy"]:
        warnings.append("旧 queries.json 措辞为开发者自拟（D.83 已承认），只能作对照，不能作基线")

    status = dataset["provenance"].get("status")
    if status == "real_teacher" and by_origin.get("simulated_candidate"):
        warnings.append("provenance.status=real_teacher，但条目里含 simulated_candidate")
    if status == "real_teacher" and not dataset["provenance"].get("real_teacher_confirmed"):
        warnings.append("provenance.status=real_teacher，但 real_teacher_confirmed 不是 true")

    if not dataset["legacy"] and queries:
        total = len(queries)
        if not (20 <= total <= 40):
            warnings.append(f"问题集共 {total} 条，目标 20–40 条（5 类各 4–8 条）")
        for category in CATEGORIES:
            count = by_category.get(category, 0)
            if count == 0:
                warnings.append(f"类别「{category}」没有条目")
            elif not (4 <= count <= 8):
                warnings.append(f"类别「{category}」有 {count} 条，建议 4–8 条")

    return errors, warnings


def select_queries(dataset: dict, include_untrusted: bool) -> tuple[list[dict], list[dict]]:
    """Return (scored, excluded). Only judgeable queries with an accepted origin get scored."""
    scored: list[dict] = []
    excluded: list[dict] = []
    for query in dataset["queries"]:
        if query["origin"] != "teacher" and not include_untrusted:
            excluded.append(
                {
                    "id": query["id"],
                    "reason": f"来源={query['origin']}，不是真人教师问题（加 --include-untrusted 才纳入）",
                }
            )
            continue
        if not query["expect_any"]:
            excluded.append({"id": query["id"], "reason": "expect.any 为空，无法判定命中"})
            continue
        scored.append(query)
    return scored, excluded


# ── judging ─────────────────────────────────────────────────────────────────────


def _object_matches(hit: dict, object_type: str) -> bool:
    if object_type in ("any", "chunk"):
        return True
    is_question = bool(hit.get("question_id"))
    if object_type == "question":
        return is_question
    if object_type == "paragraph":
        return not is_question
    return False


def _field_value(hit: dict, field: str) -> str:
    if field == "text":
        return f"{hit.get('excerpt') or ''}\n{hit.get('source_title') or ''}"
    if field == "excerpt":
        return str(hit.get("excerpt") or "")
    if field == "title":
        return str(hit.get("source_title") or "")
    if field == "knowledge_points":
        return "\n".join(str(point) for point in (hit.get("knowledge_points") or []))
    if field == "year":
        return "" if hit.get("year") is None else str(hit.get("year"))
    if field == "paper":
        return str(hit.get("source_paper") or "")
    if field == "source_type":
        return str(hit.get("source_type") or "")
    if field == "question_type":
        return str(hit.get("question_type") or "")
    return ""


def clause_matches(hit: dict, clause: dict) -> bool:
    if "all" in clause:
        return all(clause_matches(hit, sub_clause) for sub_clause in clause["all"])
    if not _object_matches(hit, clause.get("object", "any")):
        return False
    field = clause.get("field", "text")
    if field == "knowledge_points" and "equals" in clause:
        return clause["equals"] in (hit.get("knowledge_points") or [])
    value = _field_value(hit, field)
    if "equals" in clause:
        return value == clause["equals"]
    return clause["contains"] in value


def _hit_summary(hit: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "chunk_id": hit.get("chunk_id"),
        "question_id": hit.get("question_id"),
        "source_type": hit.get("source_type"),
        "source_title": hit.get("source_title"),
        "source_paper": hit.get("source_paper"),
        "year": hit.get("year"),
        "locator": hit.get("locator"),
        "knowledge_points": list(hit.get("knowledge_points") or []),
        "excerpt": (hit.get("excerpt") or "")[:160],
    }


def judge_query(hits: list[dict], query: dict, k: int) -> dict:
    """Judge one query against the top-k hits.

    lenient hit: the first hit matching any expect.any clause. This is the main
    Recall@k / MRR signal ("a relevant object came back").
    strict hit: the first hit matching the strict clause, which points at one
    specific object ("that object came back"), optionally requiring it to be a
    question chunk or a paragraph chunk.
    """
    top = hits[:k]
    row = {
        "id": query["id"],
        "category": query["category"],
        "text": query["text"],
        "origin": query["origin"],
        "object_type": query["object_type"],
        "expect_verified": query["expect_verified"],
        "strict_expected": query["strict"] is not None,
        "hits": len(top),
        "lenient_rank": None,
        "strict_rank": None,
    }
    for position, hit in enumerate(top, 1):
        if row["lenient_rank"] is None and any(
            clause_matches(hit, clause) for clause in query["expect_any"]
        ):
            row["lenient_rank"] = position
        if row["strict_rank"] is None and query["strict"] is not None:
            if clause_matches(hit, query["strict"]):
                row["strict_rank"] = position
        if row["lenient_rank"] is not None and (
            query["strict"] is None or row["strict_rank"] is not None
        ):
            break
    row["status"] = "empty" if not top else ("hit" if row["lenient_rank"] else "miss")
    row["top_hits"] = [_hit_summary(hit, index) for index, hit in enumerate(top, 1)]
    return row


# ── metrics ─────────────────────────────────────────────────────────────────────


def compute_metrics(rows: list[dict], k: int) -> dict:
    total = len(rows)
    if total == 0:
        return {
            "k": k,
            "queries": 0,
            "found": 0,
            "recall_at_k": None,
            "mrr": None,
            "empty": 0,
            "empty_rate": None,
            "hits_but_miss": 0,
            "avg_hits": None,
            "strict_total": 0,
            "strict_found": 0,
            "strict_recall": None,
            "strict_mrr": None,
        }
    found = [row["lenient_rank"] for row in rows if row["lenient_rank"] is not None]
    empty = sum(1 for row in rows if row["hits"] == 0)
    hits_but_miss = sum(
        1 for row in rows if row["hits"] > 0 and row["lenient_rank"] is None
    )
    strict_rows = [row for row in rows if row["strict_expected"]]
    strict_found = [row["strict_rank"] for row in strict_rows if row["strict_rank"] is not None]
    return {
        "k": k,
        "queries": total,
        "found": len(found),
        "recall_at_k": round(len(found) / total, 4),
        "mrr": round(sum(1.0 / rank for rank in found) / total, 4),
        "empty": empty,
        "empty_rate": round(empty / total, 4),
        "hits_but_miss": hits_but_miss,
        "avg_hits": round(sum(row["hits"] for row in rows) / total, 2),
        "strict_total": len(strict_rows),
        "strict_found": len(strict_found),
        "strict_recall": round(len(strict_found) / len(strict_rows), 4) if strict_rows else None,
        "strict_mrr": (
            round(sum(1.0 / rank for rank in strict_found) / len(strict_rows), 4)
            if strict_rows
            else None
        ),
    }


def trust_state(dataset: dict, rows: list[dict], mode: str) -> dict:
    reasons: list[str] = []
    if mode != "real":
        reasons.append("本次是自测样例（假数据），不是真实检索结果")
    untrusted = sorted({row["origin"] for row in rows if row["origin"] != "teacher"})
    for origin in untrusted:
        reasons.append(f"含来源 {ORIGIN_LABELS.get(origin, origin)}（{origin}）的条目")
    unverified = [row for row in rows if not row["expect_verified"]]
    if unverified:
        reasons.append(f"{len(unverified)} 条期望未在语料中核验（expect_verified=false）")
    status = dataset["provenance"].get("status")
    if status != "real_teacher":
        reasons.append(f"问题集 provenance.status={status!r}，不是 real_teacher")
    if dataset["legacy"]:
        reasons.append("旧 queries.json 为开发者自拟措辞（D.83）")
    return {"trustworthy_baseline": not reasons, "reasons": reasons}


# ── report ──────────────────────────────────────────────────────────────────────


def build_report(
    *,
    dataset: dict,
    rows: list[dict],
    excluded: list[dict],
    k: int,
    mode: str,
    database_url: str | None = None,
) -> dict:
    metrics = compute_metrics(rows, k)
    by_category = {}
    for category in CATEGORIES:
        subset = [row for row in rows if row["category"] == category]
        if subset:
            by_category[category] = compute_metrics(subset, k)

    origins = Counter(row["origin"] for row in rows)
    objects = Counter(row["object_type"] or "未标注" for row in rows)
    generated = datetime.now().astimezone()
    return {
        "schema": "chilon-retrieval-eval/v1",
        "report_version": "1.0",
        "generated_at": generated.isoformat(timespec="seconds"),
        "mode": mode,
        "run": {
            "k": k,
            "git_commit": _git_commit(),
            "python": sys.version.split()[0],
            "evaluator": _rel(Path(__file__)),
            "retrieval": "app.tools.impl.knowledge_search",
            "retrieval_mode": "system_session（平台语料；见 README 的 RLS 说明）",
            "database_url": _mask_url(database_url) if database_url else None,
        },
        "dataset": {
            "path": dataset["path_label"],
            "sha256": dataset["sha256"],
            "version": dataset["version"],
            "note": dataset["note"],
            "template": dataset["template"],
            "provenance": dataset["provenance"],
            "total_queries": len(dataset["queries"]),
            "scored_queries": len(rows),
            "excluded_queries": excluded,
            "scored_origins": dict(origins),
            "scored_object_types": dict(objects),
            "unverified_expectations": sum(1 for row in rows if not row["expect_verified"]),
        },
        "trust": trust_state(dataset, rows, mode),
        "metrics": metrics,
        "by_category": by_category,
        "queries": rows,
    }


def render_markdown(report: dict) -> str:
    run = report["run"]
    metrics = report["metrics"]
    trust = report["trust"]
    dataset = report["dataset"]
    k = run["k"]
    lines: list[str] = []
    lines.append("# 检索评测报告")
    lines.append("")
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append(f"- 模式：{report['mode']}")
    lines.append(f"- 问题集：`{dataset['path']}`（sha256 `{dataset['sha256'][:16]}…`，版本 {dataset['version']}）")
    lines.append(f"- 检索实现：`{run['retrieval']}`，top-k = {k}")
    lines.append(f"- 评分条数：{dataset['scored_queries']} / {dataset['total_queries']}（排除 {len(dataset['excluded_queries'])} 条）")
    if run.get("database_url"):
        lines.append(f"- 数据库：`{run['database_url']}`")
    lines.append("")
    if trust["trustworthy_baseline"]:
        lines.append("> **可信基线：是。** 全部条目为真人教师问题，期望已核验。")
    else:
        lines.append("> **可信基线：否。不得引用为本轮检索质量基线。**")
        for reason in trust["reasons"]:
            lines.append(f"> - {reason}")
    lines.append("")

    lines.append(f"## 总体指标（k = {k}）")
    lines.append("")
    lines.append("| 指标 | 值 | 定义 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| Recall@{k} | {_pct(metrics['recall_at_k'])}（{metrics['found']}/{metrics['queries']}） "
        f"| top-{k} 内出现任一 expect.any 命中 |"
    )
    lines.append(
        f"| MRR@{k} | {_num(metrics['mrr'])} | 首个 expect.any 命中排名的倒数均值（未命中记 0） |"
    )
    lines.append(
        f"| 空结果率 | {_pct(metrics['empty_rate'])}（{metrics['empty']}/{metrics['queries']}） "
        f"| 返回 0 个块 |"
    )
    lines.append(
        f"| 有结果但不对 | {metrics['hits_but_miss']}/{metrics['queries']} "
        f"| 返回了块，但没有一条满足 expect.any |"
    )
    lines.append(f"| 平均命中数 | {_num(metrics['avg_hits'], 2)} | top-{k} 平均返回块数 |")
    lines.append(
        f"| strict Recall@{k} | {_pct(metrics['strict_recall'])}"
        f"（{metrics['strict_found']}/{metrics['strict_total']}） | 指定目标对象进入 top-{k} |"
    )
    lines.append(
        f"| strict MRR@{k} | {_num(metrics['strict_mrr'])} | 指定目标对象排名的倒数均值 |"
    )
    lines.append("")

    lines.append("## 分类指标")
    lines.append("")
    lines.append(f"| 类别 | 条数 | Recall@{k} | MRR@{k} | 空结果率 | strict |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for category in CATEGORIES:
        subset = report["by_category"].get(category)
        if not subset:
            continue
        strict = (
            f"{subset['strict_found']}/{subset['strict_total']}"
            if subset["strict_total"]
            else "无"
        )
        lines.append(
            f"| {category} | {subset['queries']} | {_pct(subset['recall_at_k'])} "
            f"| {_num(subset['mrr'])} | {_pct(subset['empty_rate'])} | {strict} |"
        )
    lines.append("")

    lines.append("## 逐条结果")
    lines.append("")
    lines.append(f"| id | 类别 | 来源 | 命中数 | 相关排名 | strict 排名 | 状态 | 问题 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | --- | --- |")
    for row in report["queries"]:
        lines.append(
            f"| {row['id']} | {row['category']} | {ORIGIN_LABELS.get(row['origin'], row['origin'])} "
            f"| {row['hits']} | {row['lenient_rank'] or '—'} | {row['strict_rank'] or '—'} "
            f"| {row['status']} | {_md_cell(row['text'], 24)} |"
        )
    lines.append("")

    if dataset["excluded_queries"]:
        lines.append("## 被排除的条目")
        lines.append("")
        lines.append("| id | 原因 |")
        lines.append("| --- | --- |")
        for item in dataset["excluded_queries"]:
            lines.append(f"| {item['id']} | {_md_cell(item['reason'], 72)} |")
        lines.append("")

    lines.append("## 口径提醒")
    lines.append("")
    lines.append("- `命中` 指返回块满足任一 `expect.any` 子句；`strict` 指满足 `expect.strict` 指向的具体对象。")
    lines.append("- 空结果与“有结果但不对”分开统计：前者是检索没返回，后者是返回了不相关块。")
    lines.append("- 旧 `queries.json` 与模拟候选不得当作基线；真实基线必须来自 `origin=teacher` 且期望已核验的问题集。")
    lines.append("")
    return "\n".join(lines)


def write_report(
    report: dict,
    *,
    out_prefix: Path,
    out_json: Path | None = None,
    out_md: Path | None = None,
) -> tuple[Path, Path]:
    json_path = out_json or Path(str(out_prefix) + ".json")
    md_path = out_md or Path(str(out_prefix) + ".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(report) + "\n", encoding="utf-8")
    return json_path, md_path


def print_summary(report: dict, json_path: Path, md_path: Path) -> None:
    run = report["run"]
    metrics = report["metrics"]
    dataset = report["dataset"]
    trust = report["trust"]
    k = run["k"]
    print()
    print(f"问题集      : {dataset['path']}  (v{dataset['version']}, sha256 {dataset['sha256'][:12]}…)")
    print(f"评分条数    : {metrics['queries']}/{dataset['total_queries']}  (排除 {len(dataset['excluded_queries'])} 条)")
    print(f"可信基线    : {'是' if trust['trustworthy_baseline'] else '否'}")
    for reason in trust["reasons"]:
        print(f"              - {reason}")
    print()
    print(f"Recall@{k:<3}     : {metrics['found']}/{metrics['queries']} = {_pct(metrics['recall_at_k'])}")
    print(f"MRR@{k:<6}     : {_num(metrics['mrr'])}")
    print(f"空结果      : {metrics['empty']}/{metrics['queries']} = {_pct(metrics['empty_rate'])}")
    print(f"有结果但不对: {metrics['hits_but_miss']}/{metrics['queries']}")
    print(f"平均命中数  : {_num(metrics['avg_hits'], 2)}")
    if metrics["strict_total"]:
        print(
            f"strict      : {metrics['strict_found']}/{metrics['strict_total']} = "
            f"{_pct(metrics['strict_recall'])}  (MRR {_num(metrics['strict_mrr'])})"
        )
    else:
        print("strict      : 问题集里没有 strict 期望（无法计算）")
    print()
    print(f"JSON 报告   : {_rel(json_path)}")
    print(f"Markdown    : {_rel(md_path)}")


# ── DB path ─────────────────────────────────────────────────────────────────────


class Blocked(Exception):
    def __init__(self, code: int, title: str, reasons: list[str], steps: list[str] | None = None):
        super().__init__(title)
        self.code = code
        self.title = title
        self.reasons = reasons
        self.steps = steps or []


def _preflight(url: str, timeout: float = 2.0) -> str | None:
    """Return a human reason when a TCP DB host does not listen, else None."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or 5432
    except ValueError:
        return None
    if not host or host.startswith("/"):
        return None  # unix socket DSN: nothing to preflight
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return f"{host}:{port} 无监听或不可达（{type(exc).__name__}: {exc}）"


def _run_db_eval(
    scored: list[dict], k: int, limit: int, url: str
) -> list[dict]:
    """Run the real retrieval and return per-query judged rows. Raises Blocked."""
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.db import session as db
        from app.tools import impl as tools_impl
    except ModuleNotFoundError as exc:
        raise Blocked(
            EXIT_NO_DEPS,
            "缺少 Python 依赖",
            [f"导入后端模块失败：No module named {exc.name!r}"],
            [
                "评测要走后端真实检索，需要 .venv 里的依赖。",
                r"改用：.\.venv\Scripts\python.exe tools\eval_retrieval.py ...",
            ],
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a traceback
        raise Blocked(
            EXIT_NO_DEPS,
            "后端模块导入失败",
            [f"{type(exc).__name__}: {exc}"],
            [r"改用：.\.venv\Scripts\python.exe tools\eval_retrieval.py ..."],
        ) from exc

    import uuid as uuid_module

    def tool_context(topic: str) -> object:
        return tools_impl.ToolContext(
            owner_id=uuid_module.uuid4(),
            execution_id=uuid_module.uuid4(),
            step_key="retrieval-eval",
            spec={"limit": limit},
            requirement={"topic": topic, "sources": []},
            deps={},
        )

    async def _inner() -> list[dict]:
        initialized = False
        rows: list[dict] = []
        try:
            db.init(url)
            initialized = True
            for query in scored:
                async with db.system_session() as session:
                    result = await tools_impl.knowledge_search(
                        session, tool_context(query["text"])
                    )
                hits = result.get("hits") or []
                rows.append(judge_query(hits, query, k))
        finally:
            if initialized:
                await db.dispose()
        return rows

    try:
        return asyncio.run(_inner())
    except Blocked:
        raise
    except Exception as exc:  # noqa: BLE001 - connection/schema errors become exit code 5
        raise Blocked(
            EXIT_DB_FAILED,
            "数据库评测失败",
            [f"{type(exc).__name__}: {exc}"],
            [
                "确认 CHILON_TEST_DATABASE_URL 指向已建表、已导入平台语料的库。",
                "确认该账号能读 knowledge_chunks / knowledge_sources（测试用 postgres 账号可以）。",
            ],
        ) from exc


# ── self test ───────────────────────────────────────────────────────────────────


def _fake_hit(
    excerpt: str,
    *,
    title: str = "来源标题",
    question_id: str | None = "q-1",
    knowledge_points: list[str] | None = None,
    year: object = None,
    paper: str | None = None,
    source_type: str = "gaokao_paper",
) -> dict:
    return {
        "chunk_id": f"chunk-{abs(hash(excerpt)) % 10000}",
        "question_id": question_id,
        "source_title": title,
        "excerpt": excerpt,
        "knowledge_points": knowledge_points or [],
        "year": year,
        "source_paper": paper,
        "source_type": source_type,
        "locator": "p.1",
    }


def _selftest() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        results.append((name, bool(condition), detail))

    # 1. 旧格式归一化
    legacy = _normalize_query(
        {"id": "L1", "category": "主题词", "text": "导数", "expect_any": ["导数"], "target": "x^3 + bx"},
        0,
    )
    check(
        "旧 queries.json 字段归一化（expect_any/target -> 统一子句）",
        legacy["origin"] == "legacy_developer"
        and legacy["expect_any"][0]["field"] == "text"
        and legacy["strict"] is not None
        and legacy["strict"]["contains"] == "x^3 + bx"
        and legacy["expect_verified"] is False,
    )

    # 2. lenient 命中排名
    query = _normalize_query(
        {"id": "T1", "category": "主题词", "text": "导数", "expect": {"any": ["导数"]}},
        0,
    )
    hits = [_fake_hit("集合与逻辑"), _fake_hit("导数的几何意义")]
    row = judge_query(hits, query, 8)
    check("lenient 命中取第一次出现的位置", row["lenient_rank"] == 2 and row["status"] == "hit")
    check("未命中但有结果记为 miss", judge_query([_fake_hit("概率统计")], query, 8)["status"] == "miss")
    check("零命中记为 empty", judge_query([], query, 8)["status"] == "empty")

    # 3. strict 对象约束：段落块不算题目目标
    strict_query = _normalize_query(
        {
            "id": "T2",
            "category": "教材概念",
            "text": "补集",
            "expect": {
                "any": ["补集"],
                "strict": {"object": "question", "field": "text", "contains": "不属于集合A"},
            },
        },
        0,
    )
    strict_hits = [
        _fake_hit("补集：由全集U中不属于集合A的元素组成", question_id=None),
        _fake_hit("补集相关题目：由全集U中不属于集合A的元素组成", question_id="q-9"),
    ]
    strict_row = judge_query(strict_hits, strict_query, 8)
    check(
        "strict 的 object=question 约束生效（段落块跳过，排名取第 2）",
        strict_row["lenient_rank"] == 1
        and strict_row["strict_rank"] == 2
        and strict_row["strict_expected"],
    )

    # 4. Recall / MRR / 空结果 / 有结果但不对 的算术
    metrics_rows = [
        dict(judge_query([_fake_hit("导数")], query, 8)),
        dict(judge_query([_fake_hit("a"), _fake_hit("b"), _fake_hit("导数")], query, 8)),
        dict(judge_query([], query, 8)),
        dict(judge_query([_fake_hit("概率")], query, 8)),
    ]
    for item in metrics_rows:
        item["strict_expected"] = False
    metrics = compute_metrics(metrics_rows, 8)
    check(
        "指标算术：Recall=2/4、MRR=(1+1/3)/4、空结果=1/4、有结果但不对=1",
        metrics["found"] == 2
        and metrics["recall_at_k"] == 0.5
        and metrics["mrr"] == round((1 + 1 / 3) / 4, 4)
        and metrics["empty"] == 1
        and metrics["empty_rate"] == 0.25
        and metrics["hits_but_miss"] == 1,
        f"{metrics}",
    )
    strict_metrics = compute_metrics([strict_row], 8)
    check(
        "strict 指标：1/1、strict MRR=0.5",
        strict_metrics["strict_total"] == 1
        and strict_metrics["strict_recall"] == 1.0
        and strict_metrics["strict_mrr"] == 0.5,
    )
    check("空集合不除零", compute_metrics([], 8)["recall_at_k"] is None)

    # 5. 年份等元数据用 equals 判定，而不是在题干里碰运气
    meta_query = _normalize_query(
        {
            "id": "T3",
            "category": "年份+卷别",
            "text": "2024 新课标Ⅰ卷",
            "expect": {"any": [{"field": "year", "equals": "2024"}]},
        },
        0,
    )
    meta_hit = _fake_hit("某道题", year=2024, paper="新课标Ⅰ卷")
    meta_miss = _fake_hit("2024 出现在题干里", year=2023, paper="北京卷")
    check(
        "meta 字段 equals 判定（year=2024 命中，题干含 2024 但 year=2023 不命中）",
        judge_query([meta_hit], meta_query, 8)["lenient_rank"] == 1
        and judge_query([meta_miss], meta_query, 8)["lenient_rank"] is None,
    )

    # 5b. AND 组：年份 + 卷别必须同时满足
    compound_query = _normalize_query(
        {
            "id": "T4",
            "category": "年份+卷别",
            "text": "2024 新课标Ⅰ卷",
            "expect": {
                "any": [
                    {
                        "all": [
                            {"field": "year", "equals": "2024"},
                            {"field": "paper", "contains": "新课标Ⅰ卷"},
                        ]
                    }
                ]
            },
        },
        0,
    )
    check(
        "AND 组：先年月对但卷别错不算命中，两项都对才算",
        judge_query([_fake_hit("题目", year=2024, paper="北京卷")], compound_query, 8)["lenient_rank"] is None
        and judge_query([_fake_hit("题目", year=2024, paper="新课标Ⅰ卷")], compound_query, 8)["lenient_rank"] == 1,
    )

    # 6. top-k 截断：第 k+1 位出现不算命中
    deep_hits = [_fake_hit("无关") for _ in range(8)] + [_fake_hit("导数")]
    check(
        "top-k 截断：第 9 位的命中不计入 Recall@8",
        judge_query(deep_hits, query, 8)["lenient_rank"] is None
        and judge_query(deep_hits, query, 8)["hits"] == 8,
    )

    # 7. 校验器：空白模板/重复 id/非法类别
    template_dataset = {
        "queries": [
            {
                "id": "Q-A-01",
                "category": "主题词",
                "text": "",
                "origin": "teacher",
                "expect": {"any": []},
                "expect_verified": False,
                "contributor": "",
                "collected_at": "",
                "object_type": "",
                "strict": None,
                "expect_any": [],
                "notes": "",
                "legacy": False,
            }
        ],
        "path": Path("<selftest>"),
        "path_label": "<selftest>",
        "sha256": "0" * 64,
        "version": "teacher-questions/v1",
        "note": "",
        "template": True,
        "provenance": {"status": "template", "real_teacher_confirmed": False},
        "legacy": False,
    }
    errors, warnings = validate_dataset(template_dataset)
    check(
        "空白模板被判为不可运行",
        any("text 为空" in error for error in errors) and any("空白收集模板" in warning for warning in warnings),
    )
    try:
        _normalize_query({"id": "X1", "category": "不存在的类别", "text": "x"}, 0)
        bad_category_caught = False
    except DatasetError:
        bad_category_caught = True
    check("非法 category 被拒绝", bad_category_caught)
    try:
        _normalize_query(
            {
                "id": "X2",
                "category": "主题词",
                "text": "x",
                "expect": {"any": [{"field": "nope", "contains": "x"}]},
            },
            0,
        )
        bad_field_caught = False
    except DatasetError:
        bad_field_caught = True
    check("非法 expect.field 被拒绝", bad_field_caught)

    # 8. 不可信来源的识别
    simulated_dataset = {
        "provenance": {"status": "simulated"},
        "legacy": False,
    }
    simulated_rows = [
        {
            "origin": "simulated_candidate",
            "expect_verified": False,
        }
    ]
    trust = trust_state(simulated_dataset, simulated_rows, "real")
    check(
        "模拟候选会被标记为不可信基线",
        trust["trustworthy_baseline"] is False and len(trust["reasons"]) >= 3,
        f"{trust}",
    )

    # 9. 报告 JSON/MD 渲染可用
    fake_dataset = {
        "path": Path("<selftest>"),
        "path_label": "var/retrieval/selftest-fixture.json",
        "sha256": "f" * 64,
        "version": "teacher-questions/selftest",
        "note": "自测样例，非真实数据",
        "template": False,
        "provenance": {"status": "simulated", "real_teacher_confirmed": False},
        "legacy": False,
        "queries": [query, strict_query],
        "total_queries": 2,
    }
    fake_rows = [
        dict(judge_query([_fake_hit("导数")], query, 8)),
        dict(judge_query(strict_hits, strict_query, 8)),
    ]
    for item in fake_rows:
        item.setdefault("strict_expected", False)
    fake_rows[1]["strict_expected"] = True
    report = build_report(
        dataset=fake_dataset,
        rows=fake_rows,
        excluded=[{"id": "SIM-01", "reason": "模拟候选"}],
        k=8,
        mode="selftest",
        database_url="postgresql+psycopg://postgres:secret@localhost:5432/chilon",
    )
    dumped = json.dumps(report, ensure_ascii=False)
    markdown = render_markdown(report)
    check(
        "报告可序列化为 JSON 且 Markdown 含关键指标与不可信声明",
        "Recall@8" in markdown
        and "可信基线：否" in markdown
        and "secret" not in dumped
        and report["trust"]["trustworthy_baseline"] is False,
    )
    check(
        "报告里数据库口令被掩码",
        "***" in (report["run"]["database_url"] or ""),
        str(report["run"]["database_url"]),
    )

    return results


def _write_selftest_demo() -> tuple[Path, Path]:
    """Render a report from fake hits so JSON/MD output paths are exercised too."""
    query = _normalize_query(
        {
            "id": "ST-01",
            "category": "主题词",
            "text": "导数",
            "expect": {"any": ["导数"]},
        },
        0,
    )
    strict_query = _normalize_query(
        {
            "id": "ST-02",
            "category": "教材概念",
            "text": "补集的定义",
            "expect": {
                "any": ["补集"],
                "strict": {"object": "question", "field": "text", "contains": "不属于集合A"},
            },
        },
        0,
    )
    rows = [
        dict(judge_query([_fake_hit("导数的几何意义")], query, 8)),
        dict(
            judge_query(
                [
                    _fake_hit("补集：由全集U中不属于集合A的元素组成", question_id=None),
                    _fake_hit("补集相关题目：由全集U中不属于集合A的元素组成", question_id="q-9"),
                ],
                strict_query,
                8,
            )
        ),
    ]
    for item in rows:
        item["strict_expected"] = item["id"] == "ST-02"
    dataset = {
        "path": Path("<selftest>"),
        "path_label": "var/retrieval/selftest.{json,md}",
        "sha256": "0" * 64,
        "version": "teacher-questions/selftest",
        "note": "自测样例：假命中，不是真实检索结果",
        "template": False,
        "provenance": {"status": "selftest", "real_teacher_confirmed": False},
        "legacy": False,
        "queries": [query, strict_query],
        "total_queries": 2,
    }
    report = build_report(
        dataset=dataset,
        rows=rows,
        excluded=[],
        k=8,
        mode="selftest",
        database_url=None,
    )
    return write_report(report, out_prefix=DEFAULT_OUT_PREFIX.parent / "selftest")


def run_selftest() -> int:
    results = _selftest()
    failed = [item for item in results if not item[1]]
    for name, ok, detail in results:
        suffix = f"  [{detail}]" if detail and not ok else ""
        print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")
    print()
    if failed:
        print(f"自测失败：{len(failed)}/{len(results)}")
        return EXIT_SELFTEST_FAILED
    json_path, md_path = _write_selftest_demo()
    print(f"自测通过：{len(results)}/{len(results)}")
    print(f"自测样例报告（假数据，非基线）：{_rel(json_path)}")
    print(f"                               {_rel(md_path)}")
    return EXIT_OK


# ── check-input / run ───────────────────────────────────────────────────────────


def print_dataset_header(dataset: dict) -> None:
    by_category = Counter(query["category"] for query in dataset["queries"])
    by_origin = Counter(query["origin"] for query in dataset["queries"])
    print(f"问题集    : {dataset['path_label']}")
    print(f"版本      : {dataset['version']}   来源状态: {dataset['provenance'].get('status')}")
    print(f"条数      : {len(dataset['queries'])}")
    print("类别分布  : " + "，".join(f"{category} {by_category.get(category, 0)}" for category in CATEGORIES))
    print("来源分布  : " + "，".join(f"{ORIGIN_LABELS.get(origin, origin)} {count}" for origin, count in by_origin.items()))


def run_check_input(dataset: dict, include_untrusted: bool) -> int:
    errors, warnings = validate_dataset(dataset)
    scored, excluded = select_queries(dataset, include_untrusted)
    print_dataset_header(dataset)
    if dataset["template"]:
        filled = sum(1 for query in dataset["queries"] if query["text"])
        total = len(dataset["queries"])
        print(f"模板进度  : {filled}/{total} 条已填写")
        template_errors = [error for error in errors if "text 为空" not in error]
        if template_errors:
            print()
            print("结构问题：")
            for error in template_errors[:20]:
                print(f"  - {error}")
        print()
        print("结论：这是问题收集模板，不是可运行问题集。")
        print(f"      按模板内的 instructions 填写后另存为 {_rel(DEFAULT_INPUT)} 再评测。")
        return EXIT_NO_DATA
    judgeable = sum(1 for query in dataset["queries"] if query["expect_any"])
    strict_total = sum(1 for query in dataset["queries"] if query["strict"])
    verified = sum(1 for query in dataset["queries"] if query["expect_verified"])
    print(f"可判定    : {judgeable} 条（expect.any 非空）")
    print(f"strict    : {strict_total} 条")
    print(f"已核验期望: {verified} 条")
    print(f"默认评分  : {len(scored)} 条（排除 {len(excluded)} 条）")

    def _show(items: list[str], title: str, limit: int = 20) -> None:
        if not items:
            return
        print()
        print(f"{title}（{len(items)} 条）：")
        for item in items[:limit]:
            print(f"  - {item}")
        if len(items) > limit:
            print(f"  ... 还有 {len(items) - limit} 条")

    _show(errors, "错误")
    _show(warnings, "警告")

    print()
    if errors:
        print("结论：不可运行（存在错误）。")
        return EXIT_NO_DATA
    print("结论：结构校验通过。")
    if not scored:
        print("      但没有可评分的条目：真实教师问题还没到位，或期望尚未核验。")
    return EXIT_OK


def run_eval(args: argparse.Namespace, dataset: dict) -> int:
    if dataset["template"]:
        filled = sum(1 for query in dataset["queries"] if query["text"])
        total = len(dataset["queries"])
        print("无法评测：这是问题收集模板，不是可运行问题集。")
        print()
        print(f"模板进度：{filled}/{total} 条已填写。")
        print("按模板内的 instructions 填写后另存为 corpus/eval/teacher_questions.json。")
        print(f"退出码：{EXIT_NO_DATA}")
        return EXIT_NO_DATA

    errors, warnings = validate_dataset(dataset)
    if errors:
        print("无法评测：问题集不合法。")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... 还有 {len(errors) - 20} 条")
        print()
        print("先修问题集；模板见 corpus/eval/teacher_questions.template.json。")
        print(f"退出码：{EXIT_NO_DATA}")
        return EXIT_NO_DATA

    scored, excluded = select_queries(dataset, args.include_untrusted)
    print_dataset_header(dataset)
    print(f"默认评分  : {len(scored)} 条（排除 {len(excluded)} 条）")
    for warning in warnings:
        print(f"警告      : {warning}")
    print()

    if not scored:
        teacher_count = sum(1 for query in dataset["queries"] if query["origin"] == "teacher")
        print("无法评测：没有可评分的条目。")
        print()
        print("原因：")
        print(f"  - 真人教师问题：{teacher_count} 条（默认只评这一来源）")
        print(f"  - 模拟候选/旧自拟：{sum(1 for query in dataset['queries'] if query['origin'] != 'teacher')} 条（默认排除）")
        print(f"  - 期望为空、无法判定的：{sum(1 for query in dataset['queries'] if not query['expect_any'])} 条")
        print()
        print("下一步：")
        print("  1. 按 corpus/eval/README_retrieval.md 收集真人教师问题并核验期望；")
        print("  2. 或只做工装演练：加 --include-untrusted（结果会标记为不可信基线）。")
        print(f"退出码：{EXIT_NO_DATA}")
        return EXIT_NO_DATA

    url = os.environ.get(ENV_VAR, "").strip()
    if not url:
        print(f"无法评测：{ENV_VAR} 未设置。")
        print()
        print("原因：")
        print("  - 评测必须连真实知识库；当前环境没有数据库连接串。")
        print("  - 没有数据库时本脚本不会用假数据凑一个数字。")
        print()
        print("下一步：")
        print("  1. 启动/恢复 PostgreSQL（本机 5432 或 database/tests/run_*.ps1 起的容器）；")
        print(f'  2. $env:{ENV_VAR} = "{ENV_EXAMPLE}"')
        print("  3. .\\.venv\\Scripts\\python.exe tools\\eval_retrieval.py --input corpus\\eval\\teacher_questions.json")
        print(f"退出码：{EXIT_NO_DB}")
        return EXIT_NO_DB

    if not args.no_preflight:
        problem = _preflight(url)
        if problem:
            print(f"无法评测：数据库不可达（{problem}）。")
            print()
            print("原因：")
            print("  - TCP 连接失败，说明数据库没启动、端口不对，或只监听了 unix socket。")
            print()
            print("下一步：")
            print("  1. 确认数据库已启动并监听该端口；")
            print(f"  2. 检查 $env:{ENV_VAR}（例如 {ENV_EXAMPLE}）；")
            print("  3. 若网络探测本身被环境限制，可加 --no-preflight 跳过这一步。")
            print(f"退出码：{EXIT_DB_FAILED}")
            return EXIT_DB_FAILED

    try:
        rows = _run_db_eval(scored, args.k, args.limit or args.k, url)
    except Blocked as blocked:
        print(f"无法评测：{blocked.title}。")
        print()
        for reason in blocked.reasons:
            print(f"  - {reason}")
        if blocked.steps:
            print()
            print("下一步：")
            for step in blocked.steps:
                print(f"  {step}")
        print(f"退出码：{blocked.code}")
        return blocked.code

    mode = "real" if all(row["origin"] == "teacher" for row in rows) else "mixed"
    report = build_report(
        dataset=dataset,
        rows=rows,
        excluded=excluded,
        k=args.k,
        mode=mode,
        database_url=url,
    )
    json_path, md_path = write_report(
        report, out_prefix=args.out_prefix, out_json=args.out_json, out_md=args.out_md
    )
    print_summary(report, json_path, md_path)
    print()
    print(f"退出码：{EXIT_OK}")
    return EXIT_OK


# ── CLI ─────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval_retrieval.py",
        description="检索质量评测：Recall@k / MRR / 空结果 / strict target，输出 JSON + Markdown。",
        epilog=(
            "无数据库时以退出码 2/3/4/5 给出'无法评测'的原因，不打印堆栈。"
            " 详见 corpus/eval/README_retrieval.md。"
        ),
    )
    parser.add_argument("--input", type=Path, default=None, help=f"问题集 JSON（默认 {_rel(DEFAULT_INPUT)}）")
    parser.add_argument("--k", type=int, default=8, help="top-k，默认 8")
    parser.add_argument("--limit", type=int, default=None, help="检索请求的 limit，默认与 --k 相同")
    parser.add_argument(
        "--out-prefix",
        type=Path,
        default=DEFAULT_OUT_PREFIX,
        help=f"报告输出前缀（生成 .json/.md），默认 {_rel(DEFAULT_OUT_PREFIX)}",
    )
    parser.add_argument("--out-json", type=Path, default=None, help="单独指定 JSON 输出路径")
    parser.add_argument("--out-md", type=Path, default=None, help="单独指定 Markdown 输出路径")
    parser.add_argument(
        "--include-untrusted",
        action="store_true",
        help="把模拟候选 / 旧自拟问题也纳入评分（结果标记为不可信基线）",
    )
    parser.add_argument("--check-input", action="store_true", help="只校验问题集，不连数据库")
    parser.add_argument("--selftest", action="store_true", help="用假数据自测指标逻辑，不连数据库")
    parser.add_argument("--no-preflight", action="store_true", help="跳过数据库 TCP 预检")
    return parser


def _force_utf8_stdio() -> None:
    """Windows Python defaults to the ANSI codepage (GBK here) while the terminal
    (and CI log capture) decodes UTF-8. Force UTF-8 so the Chinese report is readable
    instead of mojibake; file output is already UTF-8 either way."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.k <= 0:
        parser.error("--k 必须为正整数")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须为正整数")

    if args.selftest:
        return run_selftest()

    input_path = args.input or DEFAULT_INPUT
    try:
        dataset = load_dataset(input_path)
    except DatasetError as exc:
        print(f"无法评测：{exc}")
        print()
        if not input_path.exists():
            print("下一步：")
            print(f"  1. 用模板收集真人教师问题：{_rel(TEMPLATE_INPUT)}")
            print(f"  2. 填好后另存为：{_rel(DEFAULT_INPUT)}")
            print(f"  3. 结构校验：python tools/eval_retrieval.py --check-input --input {input_path.name}")
            print("  4. 若手上还没有真实问题，先看模拟候选（明确标注、不可作基线）：")
            print(f"     {_rel(CANDIDATES_INPUT)}")
        print(f"退出码：{EXIT_NO_DATA}")
        return EXIT_NO_DATA

    if args.check_input:
        return run_check_input(dataset, args.include_untrusted)
    return run_eval(args, dataset)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
