"""Minimal DashScope (Qwen) API client for embedding and rerank.

Used by the indexing / evaluation tools that talk to the China-region Bailian
endpoint.  Credentials and models come from the repo ``.env`` via
``backend/app/settings.py`` (``CHILON_QWEN_*``; ``DASHSCOPE_API_KEY`` is a
fallback for the key).

The client is deliberately synchronous: indexing is a background job and the
evaluation set is small (60–100 queries), so asyncio would only add complexity.

Usage:
    from qwen_api import embed_texts, rerank
    vectors, stats = embed_texts(["..."])
    scores, stats = rerank("query", ["doc1", "doc2"])
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402

DEFAULT_BATCH_SIZE = 20  # qwen3.7-text-embedding max rows per request


class QwenAPIError(RuntimeError):
    """Raised for a non-retryable API failure (bad key, model, or request)."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _api_key() -> str:
    key = config.get("CHILON_QWEN_API_KEY") or config.get("DASHSCOPE_API_KEY")
    if not key:
        raise QwenAPIError(
            "CHILON_QWEN_API_KEY 为空；先在 .env 里填百炼 API-KEY（sk-...），"
            "或设置 DASHSCOPE_API_KEY。"
        )
    return key


def _base_url() -> str:
    return (config.get("CHILON_QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")


def _timeout() -> float:
    return float(config.get("CHILON_QWEN_TIMEOUT_SECONDS") or 30)


def _post(path: str, payload: dict[str, Any], *, what: str) -> dict[str, Any]:
    import httpx  # noqa: PLC0415 - keep module import light for --help

    url = f"{_base_url()}{path}"
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    last_error: str = ""
    for attempt in range(3):
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:  # network problem: retry
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise QwenAPIError(f"{what} 返回非 JSON：{response.text[:300]}") from exc
        body = response.text[:500]
        if response.status_code in (429, 500, 502, 503, 504):
            last_error = f"HTTP {response.status_code}: {body}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 401:
            raise QwenAPIError(
                f"{what} 401：API Key 无效。请使用百炼控制台（华北2 北京）创建的 sk-... key。",
                status=401,
                body=body,
            )
        if response.status_code == 402:
            raise QwenAPIError(f"{what} 402：账户欠费/额度不足。", status=402, body=body)
        if response.status_code == 404:
            raise QwenAPIError(
                f"{what} 404：模型或路径不存在；检查 CHILON_QWEN_*_MODEL 与 BASE_URL。",
                status=404,
                body=body,
            )
        raise QwenAPIError(f"{what} HTTP {response.status_code}: {body}", status=response.status_code, body=body)
    raise QwenAPIError(f"{what} 重试 3 次仍失败：{last_error}")


def embedding_model() -> str:
    return config.get("CHILON_QWEN_EMBEDDING_MODEL") or "qwen3.7-text-embedding"


def embedding_dimension() -> int:
    return int(config.get("CHILON_QWEN_EMBEDDING_DIM") or 1024)


def rerank_model() -> str:
    return config.get("CHILON_QWEN_RERANK_MODEL") or "qwen3.7-text-rerank"


def rerank_top_n() -> int:
    return int(config.get("CHILON_QWEN_RERANK_TOP_N") or 40)


def embed_texts(
    texts: Sequence[str],
    *,
    model: str | None = None,
    dimension: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Embed texts via the native DashScope endpoint; order is preserved."""
    if not texts:
        return [], {"requests": 0, "input_tokens": 0, "seconds": 0.0, "model": model or embedding_model()}
    model = model or embedding_model()
    dimension = dimension or embedding_dimension()
    batch_size = max(1, min(batch_size, 20))

    vectors: list[list[float]] = []
    requests = 0
    input_tokens = 0
    started = time.perf_counter()
    path = "/services/embeddings/text-embedding/text-embedding"
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        body = _post(
            path,
            {
                "model": model,
                "input": {"texts": batch},
                "parameters": {"dimension": dimension},
            },
            what=f"embedding batch {start // batch_size + 1}",
        )
        requests += 1
        usage = body.get("usage") or {}
        input_tokens += int(usage.get("input_tokens") or usage.get("total_tokens") or 0)
        try:
            embeddings = body["output"]["embeddings"]
        except (KeyError, TypeError) as exc:
            raise QwenAPIError(f"embedding 响应结构异常：{str(body)[:400]}") from exc
        # DashScope returns text_index; sort defensively, then verify order.
        embeddings = sorted(embeddings, key=lambda item: int(item.get("text_index", 0)))
        batch_vectors = [item["embedding"] for item in embeddings]
        if len(batch_vectors) != len(batch):
            raise QwenAPIError(
                f"embedding 返回 {len(batch_vectors)} 条，期望 {len(batch)} 条：{str(body)[:400]}"
            )
        vectors.extend(batch_vectors)
    seconds = time.perf_counter() - started
    return vectors, {
        "model": model,
        "dimension": dimension,
        "requests": requests,
        "input_tokens": input_tokens,
        "seconds": round(seconds, 3),
        "texts": len(texts),
    }


def rerank(
    query: str,
    documents: Sequence[str],
    *,
    model: str | None = None,
    top_n: int | None = None,
) -> tuple[list[float], dict[str, Any]]:
    """Return one relevance score per input document (missing scores become 0)."""
    if not documents:
        return [], {"pairs": 0, "seconds": 0.0, "model": model or rerank_model()}
    model = model or rerank_model()
    requested_top_n = top_n or rerank_top_n()
    requested_top_n = max(1, min(requested_top_n, len(documents), 500))
    started = time.perf_counter()
    body = _post(
        "/services/rerank/text-rerank/text-rerank",
        {
            "model": model,
            "input": {"query": query, "documents": list(documents)},
            "parameters": {"top_n": requested_top_n, "return_documents": False},
        },
        what="rerank",
    )
    seconds = time.perf_counter() - started
    try:
        results = body["output"]["results"]
    except (KeyError, TypeError) as exc:
        raise QwenAPIError(f"rerank 响应结构异常：{str(body)[:400]}") from exc
    scores = [0.0] * len(documents)
    for item in results:
        index = int(item.get("index", -1))
        if 0 <= index < len(scores):
            scores[index] = float(item.get("relevance_score") or 0.0)
    return scores, {
        "model": model,
        "pairs": len(documents),
        "returned": len(results),
        "seconds": round(seconds, 3),
        "top_n": requested_top_n,
    }
