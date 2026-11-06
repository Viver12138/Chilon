"""Hybrid retrieval prototype for Chilon V1.2 stages 4-5.

This module is **not wired into the app**; it is the prototype behind
``tools/build_hybrid_index.py`` and ``tools/eval_hybrid.py``.  It adds:

* rule-based query-condition extraction (year range / paper / source type /
  question type / knowledge-point names) plus jieba keywords;
* pg_trgm lexical retrieval over ``knowledge_chunks`` (with metadata filters);
* Qdrant vector retrieval (Qwen3-Embedding-0.6B, with payload filters);
* reciprocal-rank fusion (RRF) and dedup by chunk_id;
* Qwen3-Reranker-0.6B cross-encoder reranking of the fused candidates.

All tunables live in :data:`CONFIG` and are frozen before evaluation; the
evaluation report records the exact values.  Heavy imports (torch,
transformers, qdrant_client, jieba, psycopg) are lazy so the module can be
imported without them.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

# ---------------------------------------------------------------------------
# Frozen configuration — do not tune against the 15-query evaluation set.
# ---------------------------------------------------------------------------
CONFIG: dict[str, Any] = {
    # retrieval
    "final_k": 8,
    "text_top_n": 50,
    "vector_top_n": 50,
    "rrf_k": 60,
    "rerank_candidates": 40,
    "min_filtered_hits": 8,
    # embedding
    "embed_max_length": 512,
    "embed_batch_size": 32,
    "torch_threads": 16,
    # reranker (batch 4 measured faster than 8 on this CPU: 0.51 vs 0.40 pairs/s)
    "rerank_max_length": 1024,
    "rerank_batch_size": 4,
    "rerank_doc_chars": 1200,
    "rerank_instruction": (
        "给定一条高中数学教师的教学检索请求，判断文档（题目或教材内容）是否与请求相关。"
    ),
    "embed_instruction": (
        "给定一条高中数学教师的教学检索请求，检索与该请求相关的高中数学题目或教材内容。"
    ),
    # text retrieval
    "trgm_keywords": 12,
    "trgm_min_token_len": 2,
}

GENERIC_TOKENS = {
    "整理", "总结", "方法", "专题", "常见", "问题", "类型", "重点", "讲解",
    "设计", "教学", "方案", "计划", "训练", "复习", "安排", "每天", "学生",
    "高三", "高二", "高一", "数学", "高中", "高考", "真题", "模拟", "模拟题",
    "模拟卷", "典型", "例题", "练习", "题目", "大题", "小题", "选择题",
    "填空题", "多选题", "解答题", "证明题", "压轴题", "压轴", "难度", "基础",
    "中档", "难题", "详细", "解析", "答案", "附上", "帮我", "找", "来", "出",
    "十道", "十五道", "五道", "每类", "每种", "至少", "分类", "区分", "对应",
    "知识点", "学生容易", "容易", "不会", "处理", "分析", "原因", "针对性",
    "案例", "课堂", "一节", "七天", "一轮", "系统", "常见考法", "专题复习",
    "组合", "重点讲解", "配套", "练习", "讲解", "要求", "内容", "需要",
}

PAPER_MAP: dict[str, tuple[str, ...]] = {
    "新高考一卷": ("新高考I卷", "全国I卷"),
    "新高考i卷": ("新高考I卷", "全国I卷"),
    "新高考1卷": ("新高考I卷", "全国I卷"),
    "新高考Ⅰ卷": ("新高考I卷", "全国I卷"),
    "新课标一卷": ("新高考I卷", "全国I卷"),
    "新课标i卷": ("新高考I卷", "全国I卷"),
    "新高考二卷": ("新高考II卷", "全国II卷"),
    "新高考ii卷": ("新高考II卷", "全国II卷"),
    "北京卷": ("北京卷",),
    "上海卷": ("上海卷", "上海卷（春）"),
    "天津卷": ("天津卷",),
    "全国甲卷": ("全国甲卷",),
    "全国乙卷": ("全国乙卷",),
    "全国i卷": ("全国I卷",),
    "全国ii卷": ("全国II卷",),
}

QTYPE_MAP: dict[str, tuple[str, ...]] = {
    "多选题": ("multiple_choice",),
    "选择题": ("single_choice", "multiple_choice"),
    "填空题": ("fill_blank",),
    "解答题": ("free_response",),
    "大题": ("free_response",),
    "证明题": ("free_response",),
    "压轴题": ("free_response",),
}

YEAR_RE = re.compile(r"(20\d{2})")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _rel(path: Path) -> str:
    try:
        root = Path(__file__).resolve().parents[3]
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(path)


def _git_commit() -> str | None:
    root = Path(__file__).resolve().parents[3]
    try:
        git = root / ".git"
        if git.is_file():
            return None
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            return (git / head[5:]).read_text(encoding="utf-8").strip()[:12]
        return head[:12]
    except OSError:
        return None


def _rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - measurement is best-effort
        return None


_TORCH_CONFIGURED = False


def _import_torch():
    global _TORCH_CONFIGURED
    import torch  # type: ignore

    if not _TORCH_CONFIGURED:
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        try:
            torch.set_num_threads(int(CONFIG.get("torch_threads") or max(1, (os.cpu_count() or 8))))
        except RuntimeError:
            pass
        _TORCH_CONFIGURED = True
    return torch


# ---------------------------------------------------------------------------
# query understanding
# ---------------------------------------------------------------------------


_JIEBA_READY = False


def _jieba():
    global _JIEBA_READY
    import jieba  # type: ignore
    import jieba.analyse  # type: ignore

    if not _JIEBA_READY:
        jieba.setLogLevel(20)  # silence "Building prefix dict" chatter
        _JIEBA_READY = True
    return jieba


def extract_conditions(query: str) -> dict[str, Any]:
    """Extract structured conditions + lexical keywords from a teacher query.

    Rules are intentionally conservative and fixed before evaluation:
    * ``近五年`` -> year 2022..2026, ``近三年`` -> 2024..2026, explicit ``20xx``.
    * paper names map the 新高考I lineage to both ``新高考I卷`` (2021-2024)
      and ``全国I卷`` (2025-2026) because that is the same exam across the
      corpus years.
    * question types map 选择题/填空题/解答题 to stored enum values.
    * source type: 模拟 -> mock_exam, 真题/高考 -> gaokao_paper (both when the
      query asks for 真题 and 模拟题).
    """
    text = query.strip()

    # year range
    year_range: tuple[int, int] | None = None
    explicit_years = sorted({int(match) for match in YEAR_RE.findall(text)})
    if "近五年" in text:
        year_range = (2022, 2026)
    elif "近三年" in text:
        year_range = (2024, 2026)
    elif explicit_years:
        year_range = (explicit_years[0], explicit_years[-1])

    # source types
    source_types: list[str] = []
    if "模拟" in text:
        source_types.append("mock_exam")
    if "真题" in text or "高考" in text:
        source_types.append("gaokao_paper")
    if "教材" in text:
        source_types.append("textbook")

    # paper
    lowered = text.lower()
    papers: list[str] = []
    for needle, values in PAPER_MAP.items():
        if needle in lowered or needle in text:
            for value in values:
                if value not in papers:
                    papers.append(value)

    # question type
    question_types: list[str] = []
    for needle, values in QTYPE_MAP.items():
        if needle in text:
            for value in values:
                if value not in question_types:
                    question_types.append(value)
            break

    # knowledge point names (from the authored taxonomy; record only, not a filter)
    knowledge_points: list[str] = []
    try:
        import sys

        backend = Path(__file__).resolve().parents[2]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.services import taxonomy  # type: ignore

        knowledge_points = taxonomy.tag(text)
    except Exception:  # noqa: BLE001 - optional metadata
        knowledge_points = []

    keywords = _extract_keywords(text)

    return {
        "year_range": list(year_range) if year_range else None,
        "source_types": source_types or None,
        "papers": papers or None,
        "question_types": question_types or None,
        "knowledge_points": knowledge_points,
        "keywords": keywords,
    }


def _is_math_term(token: str) -> bool:
    """Keep tokens that look like curriculum vocabulary (authored taxonomy or digits)."""
    if not token:
        return False
    if token.isdigit():
        return True
    try:
        import sys

        backend = Path(__file__).resolve().parents[2]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from app.services import taxonomy  # type: ignore

        names = {point for point, _ in taxonomy.RULES}
        keywords = {kw for _, kws in taxonomy.RULES for kw in kws}
        if token in names or token in keywords:
            return True
        # "几何" is a substring of "立体几何"/"解析几何"; keep common sub-terms.
        return any(token in name for name in names)
    except Exception:  # noqa: BLE001
        return True


def _extract_keywords(text: str) -> list[str]:
    try:
        jieba = _jieba()
    except Exception:  # noqa: BLE001 - fall back to whole-query trigram
        return []
    raw = jieba.analyse.extract_tags(text, topK=24)
    keywords: list[str] = []
    for token in raw:
        token = token.strip()
        if len(token) < CONFIG["trgm_min_token_len"]:
            continue
        if token in GENERIC_TOKENS or token in {"的", "和", "与", "按", "找", "在"}:
            continue
        if not _is_math_term(token):
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= CONFIG["trgm_keywords"]:
            break
    return keywords


# ---------------------------------------------------------------------------
# embedding-text composition (V1.2 §9.3: body + a little necessary metadata)
# ---------------------------------------------------------------------------

SOURCE_TYPE_LABELS = {
    "gaokao_paper": "高考真题",
    "mock_exam": "模拟题",
    "textbook": "教材",
    "workbook": "教辅",
    "other": "其他",
}
QTYPE_LABELS = {
    "single_choice": "单项选择题",
    "multiple_choice": "多项选择题",
    "fill_blank": "填空题",
    "free_response": "解答题",
}


def embedding_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    source_type = row.get("source_type")
    if source_type:
        parts.append(f"资料类型：{SOURCE_TYPE_LABELS.get(source_type, source_type)}")
    if row.get("year"):
        parts.append(f"年份：{row['year']}")
    if row.get("source_paper"):
        parts.append(f"试卷：{row['source_paper']}")
    if row.get("question_no"):
        parts.append(f"题号：第{row['question_no']}题")
    if row.get("question_type"):
        parts.append(f"题型：{QTYPE_LABELS.get(row['question_type'], row['question_type'])}")
    points = row.get("knowledge_points") or []
    if points:
        parts.append("知识点：" + "、".join(str(point) for point in points[:4]))
    body = (row.get("text") or "").strip()
    parts.append(("题目内容：" if row.get("question_id") else "内容：") + body)
    return "\n".join(parts)


def embedding_query_text(query: str, instruction: str | None = None) -> str:
    instruction = instruction or CONFIG["embed_instruction"]
    return f"Instruct: {instruction}\nQuery:{query}"


# ---------------------------------------------------------------------------
# model loading / inference (CPU)
# ---------------------------------------------------------------------------


def _from_pretrained_kwargs() -> dict[str, Any]:
    """transformers 4.x accepts torch_dtype; 5.x renamed it to dtype."""
    try:
        import transformers  # type: ignore

        major = int(transformers.__version__.split(".")[0])
    except Exception:  # noqa: BLE001
        major = 4
    import torch  # type: ignore

    kwargs: dict[str, Any] = {"low_cpu_mem_usage": False}
    if major >= 5:
        kwargs["dtype"] = torch.float32
    else:
        kwargs["torch_dtype"] = torch.float32
    return kwargs


def load_embedding_model(model_dir: str | Path):
    torch = _import_torch()
    from transformers import AutoModel, AutoTokenizer  # type: ignore

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), padding_side="left")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModel.from_pretrained(str(model_dir), **_from_pretrained_kwargs())
    model.eval()
    model.to("cpu")
    dim = int(getattr(model.config, "hidden_size", 0) or 0)
    return model, tokenizer, dim


def load_reranker(model_dir: str | Path):
    torch = _import_torch()
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), padding_side="left")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(str(model_dir), **_from_pretrained_kwargs())
    model.eval()
    model.to("cpu")
    return model, tokenizer


def last_token_pool(last_hidden_states, attention_mask):
    """Qwen3-Embedding pooling: last non-padding token (handles left padding)."""
    torch = _import_torch()
    left_padding = bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item())
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


def embed_texts(
    model,
    tokenizer,
    texts: Sequence[str],
    *,
    batch_size: int | None = None,
    max_length: int | None = None,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Embed texts on CPU. Returns (vectors, stats) with measured token throughput."""
    torch = _import_torch()
    batch_size = batch_size or CONFIG["embed_batch_size"]
    max_length = max_length or CONFIG["embed_max_length"]
    vectors: list[list[float]] = []
    total_tokens = 0
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            total_tokens += int(encoded["attention_mask"].sum().item())
            outputs = model(**encoded)
            pooled = last_token_pool(outputs.last_hidden_state, encoded["attention_mask"])
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.float().tolist())
    elapsed = time.perf_counter() - started
    stats = {
        "count": len(texts),
        "tokens": total_tokens,
        "seconds": round(elapsed, 3),
        "tokens_per_second": round(total_tokens / elapsed, 1) if elapsed else None,
        "items_per_second": round(len(texts) / elapsed, 2) if elapsed else None,
        "batch_size": batch_size,
        "max_length": max_length,
    }
    return vectors, stats


def embed_queries(model, tokenizer, queries: Sequence[str], *, instruction: str | None = None):
    texts = [embedding_query_text(query, instruction) for query in queries]
    return embed_texts(model, tokenizer, texts)


# reranker helpers ----------------------------------------------------------


RERANK_PREFIX = (
    '<|im_start|>system\nJudge whether the Document meets the requirements based on '
    'the Query and the Instruct provided. Note that the answer can only be "yes" or "no".'
    "<|im_end|>\n<|im_start|>user\n"
)
RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n"


def _rerank_pair(instruction: str, query: str, doc: str) -> str:
    return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"


def rerank_scores(
    model,
    tokenizer,
    query: str,
    docs: Sequence[str],
    *,
    instruction: str | None = None,
    batch_size: int | None = None,
    max_length: int | None = None,
) -> tuple[list[float], dict[str, Any]]:
    torch = _import_torch()
    instruction = instruction or CONFIG["rerank_instruction"]
    batch_size = batch_size or CONFIG["rerank_batch_size"]
    max_length = max_length or CONFIG["rerank_max_length"]
    prefix_ids = tokenizer.encode(RERANK_PREFIX, add_special_tokens=False)
    suffix_ids = tokenizer.encode(RERANK_SUFFIX, add_special_tokens=False)
    budget = max(32, max_length - len(prefix_ids) - len(suffix_ids))
    pairs = [_rerank_pair(instruction, query, doc) for doc in docs]
    scores: list[float] = []
    yes_id = tokenizer.convert_tokens_to_ids("yes")
    no_id = tokenizer.convert_tokens_to_ids("no")
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=budget,
                return_tensors="pt",
            )
            input_ids, attention_mask = [], []
            for row_ids, row_mask in zip(encoded["input_ids"], encoded["attention_mask"]):
                ids = row_ids[row_mask.bool()].tolist()
                ids = prefix_ids + ids + suffix_ids
                input_ids.append(ids)
                attention_mask.append([1] * len(ids))
            pad = tokenizer.pad_token_id
            width = max(len(ids) for ids in input_ids)
            padded_ids, padded_mask = [], []
            for ids, mask in zip(input_ids, attention_mask):
                pad_len = width - len(ids)
                # left padding (tokenizer padding_side is left)
                padded_ids.append([pad] * pad_len + ids)
                padded_mask.append([0] * pad_len + mask)
            tensor_ids = torch.tensor(padded_ids, dtype=torch.long)
            tensor_mask = torch.tensor(padded_mask, dtype=torch.long)
            logits = model(input_ids=tensor_ids, attention_mask=tensor_mask).logits[:, -1, :]
            yes = logits[:, yes_id]
            no = logits[:, no_id]
            scores.extend(torch.sigmoid(yes - no).float().tolist())
    elapsed = time.perf_counter() - started
    stats = {
        "pairs": len(pairs),
        "seconds": round(elapsed, 3),
        "pairs_per_second": round(len(pairs) / elapsed, 2) if elapsed else None,
        "batch_size": batch_size,
        "max_length": max_length,
    }
    return scores, stats


# ---------------------------------------------------------------------------
# PostgreSQL: loading rows and pg_trgm lexical retrieval
# ---------------------------------------------------------------------------


CHUNK_SELECT = """
SELECT c.id::text AS chunk_id,
       c.text_content AS text,
       c.locator::text AS locator,
       c.ordinal AS chunk_ordinal,
       dv.id::text AS document_version_id,
       dv.source_id::text AS source_id,
       s.source_type,
       s.title AS source_title,
       s.year,
       s.exam_paper AS source_paper,
       q.id::text AS question_id,
       q.question_no,
       q.current_paper_question_type AS question_type,
       ARRAY[]::text[] AS knowledge_points
FROM knowledge_chunks c
JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
JOIN knowledge_sources s ON s.id = dv.source_id
LEFT JOIN knowledge_questions q
       ON q.document_version_id = dv.id
      AND q.stem_locator = c.locator
"""


DEFAULT_KP_VOCAB = r"C:\Users\Viver\Desktop\高中数学\10_Indexes\知识点词表.md"


def load_kp_name_map(path: str | Path | None = None) -> dict[str, str]:
    """Parse ``kp_id -> Chinese name`` from the vault vocabulary table (read-only).

    The prototype must not depend on ``knowledge_questions.current_knowledge_points``
    (its representation changed during the annotation import).  Knowledge points are
    read from ``knowledge_annotations`` instead; the vocabulary file only supplies
    display names for the embedding text.
    """
    vocab_path = Path(path or DEFAULT_KP_VOCAB)
    mapping: dict[str, str] = {}
    if not vocab_path.exists():
        return mapping
    for line in vocab_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*`(kp_[0-9a-z_]+)`\s*\|\s*([^|]+?)\s*\|", line)
        if match:
            mapping[match.group(1)] = match.group(2).strip()
    return mapping


def fetch_annotation_points(conn, kp_name_map: dict[str, str] | None = None) -> dict[str, list[str]]:
    """question_id -> [kp display names] from active ``knowledge_annotations`` rows.

    ``kp_primary`` value is a kp_id string; ``kp_secondary`` value is a JSON array
    string.  Superseded rows are ignored.  This is the SSOT for knowledge points in
    the prototype, per the 2026-11-06 data policy.
    """
    name_map = kp_name_map or {}
    mapping: dict[str, list[str]] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT question_id::text, annotation_type, value"
            " FROM knowledge_annotations"
            " WHERE superseded_by IS NULL"
            "   AND annotation_type IN ('kp_primary', 'kp_secondary')"
            " ORDER BY question_id, annotation_type"
        )
        for question_id, annotation_type, value in cur.fetchall():
            if annotation_type == "kp_secondary":
                try:
                    parsed = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    parsed = [value]
                if not isinstance(parsed, list):
                    parsed = [parsed]
                ids = [str(item) for item in parsed]
            else:
                ids = [str(value)]
            names = [name_map.get(kp_id, kp_id) for kp_id in ids]
            mapping.setdefault(question_id, []).extend(names)
    return mapping


def attach_annotation_points(hits: list[dict[str, Any]], mapping: dict[str, list[str]]) -> list[dict[str, Any]]:
    for hit in hits:
        question_id = hit.get("question_id")
        if question_id and question_id in mapping:
            hit["knowledge_points"] = mapping[question_id][:4]
    return hits


def hit_from_row(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text") or ""
    return {
        "chunk_id": row["chunk_id"],
        "question_id": row.get("question_id"),
        "question_no": row.get("question_no"),
        "question_type": row.get("question_type"),
        "knowledge_points": list(row.get("knowledge_points") or []),
        "source_id": row.get("source_id"),
        "source_title": row.get("source_title"),
        "source_type": row.get("source_type"),
        "year": row.get("year"),
        "source_paper": row.get("source_paper"),
        "document_version_id": row.get("document_version_id"),
        "locator": row.get("locator"),
        "excerpt": text[:400],
        "text": text,
    }


def fetch_all_chunks(conn) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row  # type: ignore

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CHUNK_SELECT + " ORDER BY c.id")
        return [hit_from_row(row) for row in cur.fetchall()]


def fetch_chunks(conn, chunk_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    from psycopg.rows import dict_row  # type: ignore

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CHUNK_SELECT + " WHERE c.id = ANY(%(ids)s::uuid[])", {"ids": list(chunk_ids)})
        return {hit_from_row(row)["chunk_id"]: hit_from_row(row) for row in cur.fetchall()}


def _sql_filter_clauses(conditions: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if conditions.get("year_range"):
        clauses.append("s.year BETWEEN %(year_from)s AND %(year_to)s")
        params["year_from"], params["year_to"] = conditions["year_range"]
    if conditions.get("source_types"):
        clauses.append("s.source_type = ANY(%(source_types)s)")
        params["source_types"] = list(conditions["source_types"])
    if conditions.get("papers"):
        clauses.append("s.exam_paper = ANY(%(papers)s)")
        params["papers"] = list(conditions["papers"])
    if conditions.get("question_types"):
        clauses.append("q.current_paper_question_type = ANY(%(question_types)s)")
        params["question_types"] = list(conditions["question_types"])
    return clauses, params


def text_search(
    conn,
    query: str,
    conditions: dict[str, Any],
    *,
    limit: int | None = None,
    use_filters: bool = True,
) -> list[dict[str, Any]]:
    """pg_trgm lexical retrieval over knowledge_chunks."""
    from psycopg.rows import dict_row  # type: ignore

    limit = limit or CONFIG["text_top_n"]
    keywords = conditions.get("keywords") or []
    if keywords:
        patterns = [f"%{keyword}%" for keyword in keywords]
        keyword_sql = (
            "(SELECT count(*) FROM unnest(%(keywords)s::text[]) AS kw "
            "WHERE c.text_content ILIKE '%%' || kw || '%%')"
        )
        where = "c.text_content ILIKE ANY(%(patterns)s)"
        params: dict[str, Any] = {"keywords": keywords, "patterns": patterns, "query": query}
    else:
        # No extracted vocab: fall back to a whole-query substring + trigram rank.
        keyword_sql = "0"
        where = "c.text_content ILIKE %(pattern)s"
        params = {"pattern": f"%{query}%", "query": query, "keywords": []}

    filter_clauses, filter_params = _sql_filter_clauses(conditions) if use_filters else ([], {})
    if filter_clauses:
        where += " AND " + " AND ".join(filter_clauses)
        params.update(filter_params)

    sql = (
        "SELECT sub.*, similarity(sub.text, %(query)s) AS trgm_sim FROM ("
        "SELECT c.id::text AS chunk_id, c.text_content AS text, c.locator::text AS locator,"
        " c.ordinal AS chunk_ordinal, dv.id::text AS document_version_id,"
        " dv.source_id::text AS source_id, s.source_type, s.title AS source_title, s.year,"
        " s.exam_paper AS source_paper, q.id::text AS question_id, q.question_no,"
        " q.current_paper_question_type AS question_type,"
        " ARRAY[]::text[] AS knowledge_points,"
        f" {keyword_sql} AS kw_hits"
        " FROM knowledge_chunks c"
        " JOIN knowledge_document_versions dv ON dv.id = c.document_version_id"
        " JOIN knowledge_sources s ON s.id = dv.source_id"
        " LEFT JOIN knowledge_questions q ON q.document_version_id = dv.id"
        "   AND q.stem_locator = c.locator"
        f" WHERE {where}"
        ") sub "
        "ORDER BY sub.kw_hits DESC, trgm_sim DESC, sub.chunk_ordinal ASC "
        "LIMIT %(limit)s"
    )
    params["limit"] = limit
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [hit_from_row(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def qdrant_filter(conditions: dict[str, Any]):
    from qdrant_client import models as qm  # type: ignore

    must = []
    if conditions.get("year_range"):
        start, end = conditions["year_range"]
        must.append(qm.FieldCondition(key="year", range=qm.Range(gte=start, lte=end)))
    if conditions.get("source_types"):
        must.append(qm.FieldCondition(key="source_type", match=qm.MatchAny(any=conditions["source_types"])))
    if conditions.get("papers"):
        must.append(qm.FieldCondition(key="paper", match=qm.MatchAny(any=conditions["papers"])))
    if conditions.get("question_types"):
        must.append(
            qm.FieldCondition(key="question_type", match=qm.MatchAny(any=conditions["question_types"]))
        )
    return qm.Filter(must=must) if must else None


def vector_search(
    client,
    collection: str,
    vector: Sequence[float],
    *,
    conditions: dict[str, Any] | None = None,
    limit: int | None = None,
    use_filters: bool = True,
) -> list[dict[str, Any]]:
    limit = limit or CONFIG["vector_top_n"]
    flt = qdrant_filter(conditions) if (use_filters and conditions) else None
    try:
        result = client.query_points(
            collection_name=collection,
            query=list(vector),
            limit=limit,
            query_filter=flt,
            with_payload=True,
            with_vectors=False,
        )
        points = result.points
    except AttributeError:  # older qdrant-client
        points = client.search(
            collection_name=collection,
            query_vector=list(vector),
            limit=limit,
            query_filter=flt,
            with_payload=True,
            with_vectors=False,
        )
    return [
        {
            "chunk_id": point.payload.get("chunk_id") if point.payload else str(point.id),
            "vector_score": float(point.score),
            "payload": dict(point.payload or {}),
        }
        for point in points
    ]


# ---------------------------------------------------------------------------
# fusion
# ---------------------------------------------------------------------------


def rrf_fuse(ranked_lists: Iterable[Sequence[dict[str, Any]]], *, k: int | None = None) -> list[dict[str, Any]]:
    k = k or CONFIG["rrf_k"]
    scores: dict[str, float] = {}
    by_id: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
    for list_index, hits in enumerate(ranked_lists):
        for rank, hit in enumerate(hits, 1):
            chunk_id = hit["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            if chunk_id not in by_id:
                by_id[chunk_id] = hit
            sources.setdefault(chunk_id, []).append(f"{list_index}:{rank}")
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused: list[dict[str, Any]] = []
    for chunk_id, score in ordered:
        hit = dict(by_id[chunk_id])
        hit["rrf_score"] = round(score, 6)
        hit["rrf_sources"] = sources[chunk_id]
        fused.append(hit)
    return fused


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]
