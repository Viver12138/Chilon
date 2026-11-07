r"""Check that the Qwen / Bailian credentials in .env work for embedding + rerank.

Run this once after filling in `CHILON_QWEN_API_KEY`:

    .venv\Scripts\python.exe backend\tests\check_qwen.py

It calls the native DashScope API twice (one embedding batch, one rerank), so a
wrong key, wrong region/base URL or wrong model name fail with distinct messages
instead of surfacing later inside the retrieval tooling.

No API key is printed — only its length and the last four characters.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import settings as config  # noqa: E402

EMBED_SAMPLE = "高中数学：导数的几何意义是什么？"
RERANK_QUERY = "导数的几何意义"
RERANK_DOCS = [
    "导数的几何意义是曲线在某点处切线的斜率，可以用来说明函数的变化率。",
    "集合是由一些确定的对象组成的整体，元素具有确定性、互异性、无序性。",
    "函数的单调性可以用导数来判断：导数大于零时函数单调递增。",
]


def mask(key: str) -> str:
    if not key:
        return "(空)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}…{key[-4:]}（长度 {len(key)}）"


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    payload: dict,
) -> tuple[int, dict | None, str]:
    """Return (status, json-or-None, text-snippet)."""
    try:
        r = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    except httpx.TimeoutException:
        return -1, None, "请求超时"
    except httpx.HTTPError as exc:
        return -2, None, f"{type(exc).__name__}: {exc}"
    try:
        body = r.json()
    except ValueError:
        body = None
    snippet = (r.text or "")[:300].replace("\n", " ")
    return r.status_code, body, snippet


def explain_status(status: int, model: str) -> str:
    if status == 401:
        return "401：API Key 无效或未填。检查 CHILON_QWEN_API_KEY。"
    if status == 402:
        return "402：账户欠费/额度不足。"
    if status == 404:
        return f"404：模型 {model} 或接口路径不存在。检查模型名与 base URL/region。"
    if status == 429:
        return "429：触发限流，稍后重试。"
    return f"HTTP {status}"


async def main() -> int:
    s = config.load()

    print("== 配置 ==")
    print(f"  配置文件          : {config.REPO_ROOT / '.env'}")
    print(f"  API Key           : {mask(s.qwen_api_key)}")
    print(f"  Base URL          : {s.qwen_base_url}")
    print(f"  Region            : {s.qwen_region}")
    print(f"  Embedding Model   : {s.qwen_embedding_model}（dim={s.qwen_embedding_dim}）")
    print(f"  Rerank Model      : {s.qwen_rerank_model}（top_n={s.qwen_rerank_top_n}）")
    print(f"  Timeout           : {s.qwen_timeout_seconds}s")
    print()

    if not s.qwen_api_key:
        print("FAIL: CHILON_QWEN_API_KEY 为空。请先在 .env 里填写（或设置 DASHSCOPE_API_KEY）。")
        return 2

    # 阿里云 AccessKey（LTAI...）和百炼 API-KEY（sk-...）是两种凭据，混用会 401。
    if s.qwen_api_key.startswith("LTAI"):
        print("提示：当前 key 形如 LTAI...，这是阿里云 AccessKey ID，不是百炼 API-KEY。")
        print("      请到百炼控制台「API-KEY」创建 sk-... 形式的 key（中国区/华北2 北京）。")
    elif not s.qwen_api_key.startswith("sk-"):
        print("提示：百炼 API-KEY 通常以 sk- 开头；当前格式可能不对，若 401 请回控制台确认。")
    print()

    base = s.qwen_base_url.rstrip("/")
    embed_url = f"{base}/services/embeddings/text-embedding/text-embedding"
    rerank_url = f"{base}/services/rerank/text-rerank/text-rerank"

    async with httpx.AsyncClient(timeout=s.qwen_timeout_seconds) as client:
        # 1) embedding
        print(f"== Embedding == {embed_url}")
        status, body, snippet = await post_json(
            client,
            embed_url,
            s.qwen_api_key,
            {
                "model": s.qwen_embedding_model,
                "input": {"texts": [EMBED_SAMPLE]},
                "parameters": {"dimension": s.qwen_embedding_dim},
            },
        )
        if status in (-1, -2):
            print(f"FAIL: {snippet}")
            return 1
        if status != 200:
            print(f"FAIL: {explain_status(status, s.qwen_embedding_model)}")
            print(f"      响应：{snippet}")
            return 3
        try:
            vec = body["output"]["embeddings"][0]["embedding"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            print("FAIL: 响应结构不符合预期（没有 output.embeddings[0].embedding）。")
            print(f"      响应：{json.dumps(body, ensure_ascii=False)[:600] if body else snippet}")
            return 3
        usage = (body or {}).get("usage", {})
        print(f"OK: dim={len(vec)}，usage={usage}")

        # 2) rerank
        print(f"== Rerank == {rerank_url}")
        status, body, snippet = await post_json(
            client,
            rerank_url,
            s.qwen_api_key,
            {
                "model": s.qwen_rerank_model,
                "input": {"query": RERANK_QUERY, "documents": RERANK_DOCS},
                "parameters": {"top_n": s.qwen_rerank_top_n},
            },
        )
        if status in (-1, -2):
            print(f"FAIL: {snippet}")
            return 1
        if status != 200:
            print(f"FAIL: {explain_status(status, s.qwen_rerank_model)}")
            print(f"      响应：{snippet}")
            return 4
        try:
            results = body["output"]["results"]  # type: ignore[index]
        except (KeyError, TypeError):
            print("FAIL: 响应结构不符合预期（没有 output.results）。")
            print(f"      响应：{json.dumps(body, ensure_ascii=False)[:600] if body else snippet}")
            return 4
        print("OK: rerank 返回：")
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score")
            doc = RERANK_DOCS[idx] if isinstance(idx, int) and 0 <= idx < len(RERANK_DOCS) else ""
            print(f"  - index={idx} score={score:.6f}  {doc[:40]}")

    print()
    print("PASS: Qwen embedding + rerank 均可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
