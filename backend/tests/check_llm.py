"""Check that the DeepSeek credentials in .env actually work.

Run this once after filling in `CHILON_DEEPSEEK_API_KEY`:

    python backend/tests/check_llm.py

It makes one small chat completion and prints the model's reply, so a wrong key,
a wrong base URL and a wrong model name each fail with a distinct message instead
of surfacing later as a confusing planner error.

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


def mask(key: str) -> str:
    if not key:
        return "(空)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}…{key[-4:]}（长度 {len(key)}）"


async def main() -> int:
    s = config.load()

    print("== 配置 ==")
    print(f"  配置文件     : {config.REPO_ROOT / '.env'}")
    print(f"  API Key      : {mask(s.deepseek_api_key)}")
    print(f"  Base URL     : {s.deepseek_base_url}")
    print(f"  Model        : {s.deepseek_model}")
    print(f"  Timeout      : {s.deepseek_timeout_seconds}s")
    print()

    if not s.deepseek_api_key:
        print("FAIL: CHILON_DEEPSEEK_API_KEY 为空。请先在 .env 里填写。")
        return 2

    url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": s.deepseek_model,
        "messages": [
            {"role": "system", "content": "你是连通性测试，只回一个词。"},
            {"role": "user", "content": "只回复：连通"},
        ],
        "max_tokens": 16,
        "temperature": 0,
    }

    print(f"== 请求 == {url}")
    try:
        async with httpx.AsyncClient(timeout=s.deepseek_timeout_seconds) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {s.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        print(f"FAIL: 请求超时（{s.deepseek_timeout_seconds}s）。检查网络或调大超时。")
        return 1
    except httpx.HTTPError as exc:
        print(f"FAIL: 无法连接 {url} —— {type(exc).__name__}: {exc}")
        print("      若 base URL 末尾误加了 /v1，请去掉。")
        return 1

    print(f"== 响应 == HTTP {r.status_code}")
    if r.status_code == 401:
        print("FAIL: 401 未授权 —— API Key 无效或已撤销。")
        return 1
    if r.status_code == 402:
        print("FAIL: 402 余额不足 —— 该账号没有可用额度。")
        return 1
    if r.status_code == 404:
        print("FAIL: 404 —— base URL 或模型名不对。")
        print(f"      当前模型: {s.deepseek_model}；常用值: deepseek-chat / deepseek-reasoner")
        return 1
    if r.status_code != 200:
        print(f"FAIL: 非预期状态。响应体前 400 字：\n{r.text[:400]}")
        return 1

    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
    except (KeyError, IndexError, json.JSONDecodeError):
        print(f"FAIL: 响应结构不符合预期。前 400 字：\n{r.text[:400]}")
        return 1

    print(f"  模型回复     : {content!r}")
    print(f"  token 用量   : prompt {usage.get('prompt_tokens')} / completion {usage.get('completion_tokens')}")
    print()
    print("PASS: DeepSeek 凭据可用，规划器可以接真实模型了。")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
