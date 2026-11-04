"""Plan generation.

Two implementations behind one protocol:

* `TemplatePlanner` — deterministic, no network, used by the offline test suite;
* `DeepSeekPlanner` — asks the model, then **validates everything it said**.

The rule this module enforces: **the model proposes, the validators decide.** A
planner that trusts model output would let an unexecutable plan reach the approval
screen, which is exactly what the DAG check exists to prevent. So the model's
answer is treated as untrusted input: parsed, schema-checked, DAG-checked, and
checked against the tools the teacher actually has. On failure the model gets one
retry with the validator's own error message, then the turn fails loudly.

A failed turn is a good outcome here. A plausible-looking plan that calls a tool
that does not exist is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app import settings as config
from app.services import steps


class PlanGenerationFailed(Exception):
    """The planner could not produce a plan that passes validation."""


@dataclass(frozen=True)
class ToolSpec:
    key: str
    name: str
    side_effect_level: str


class Planner(Protocol):
    async def plan(self, requirement: dict[str, Any], tools: list[ToolSpec]) -> dict[str, Any]: ...


def validate_plan(content: dict[str, Any], allowed_tools: set[str]) -> list[steps.StepSpec]:
    """Structural + capability validation. Raises PlanGenerationFailed."""
    try:
        specs = steps.parse_plan(content)
    except steps.PlanDagError as exc:
        raise PlanGenerationFailed(f"plan structure is invalid: {exc}") from exc

    unknown = sorted({s.step_type for s in specs} - allowed_tools)
    if unknown:
        raise PlanGenerationFailed(
            f"plan uses tools that are not available to this teacher: {unknown}"
        )
    if len(specs) > 12:
        raise PlanGenerationFailed(f"plan has {len(specs)} steps, which exceeds the limit of 12")
    return specs


class TemplatePlanner:
    """Deterministic planning. Not AI — a template that proves the pipeline works.

    It exists so the whole flow can run offline and so the DAG/tool validation has
    something stable to reject.
    """

    async def plan(self, requirement: dict[str, Any], tools: list[ToolSpec]) -> dict[str, Any]:
        keys = {t.key for t in tools}
        if "knowledge.search" not in keys:
            raise PlanGenerationFailed("knowledge.search is not available; cannot plan retrieval")
        if "content.generate" not in keys:
            raise PlanGenerationFailed("content.generate is not available; cannot plan generation")

        count = requirement.get("question_count") or 0
        plan_steps: list[dict[str, Any]] = [
            {
                "key": "search",
                "type": "knowledge.search",
                "title": f"检索 {', '.join(requirement.get('sources') or ['平台知识库'])}",
                "depends_on": [],
            }
        ]

        if count > 8:
            # split generation so a long set does not sit in one step
            plan_steps += [
                {
                    "key": "generate-a",
                    "type": "content.generate",
                    "title": "生成前半部分",
                    "depends_on": ["search"],
                },
                {
                    "key": "generate-b",
                    "type": "content.generate",
                    "title": "生成后半部分",
                    "depends_on": ["search"],
                },
            ]
            join_needs = ["generate-a", "generate-b"]
        else:
            plan_steps.append(
                {
                    "key": "generate",
                    "type": "content.generate",
                    "title": f"生成 {count or '若干'} 道题",
                    "depends_on": ["search"],
                }
            )
            join_needs = ["generate"]

        if "quality.check" in keys:
            plan_steps.append(
                {
                    "key": "check",
                    "type": "quality.check",
                    "title": "结构、溯源与数学校验",
                    "depends_on": join_needs,
                }
            )
            join_needs = ["check"]

        if "material.create_draft" in keys:
            plan_steps.append(
                {
                    "key": "package",
                    "type": "material.create_draft",
                    "title": "生成教师版与学生版",
                    "depends_on": join_needs,
                }
            )

        return {"steps": plan_steps}


SYSTEM_PROMPT = """你是高中数学教学方案的规划器。你的唯一任务是把教师的需求拆成一个可执行的步骤图。

规则：
1. 只能使用给定的工具，工具名必须与列表中的 key 完全一致。
2. 步骤必须有唯一且简短的 key（小写字母、数字、连字符）。
3. 步骤之间的依赖用 depends_on 声明；必须是有向无环图，可以有并行分支。
4. 第一个步骤应该是检索；生成步骤依赖检索；校验步骤依赖全部生成步骤。
5. 步骤数不超过 12。
6. 只输出 JSON，不要 markdown 代码块，不要解释。

输出格式：
{"steps": [{"key": "...", "type": "<工具key>", "title": "<中文标题>", "depends_on": ["..."]}]}"""


class DeepSeekPlanner:
    """Asks DeepSeek for a plan, then validates it and may retry once."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = config.load()
        self._transport = transport or httpx.AsyncHTTPTransport()
        if not self._settings.llm_configured:
            raise PlanGenerationFailed("DeepSeek is not configured: set CHILON_DEEPSEEK_API_KEY in .env")

    async def _complete(self, messages: list[dict[str, str]]) -> str:
        s = self._settings
        url = f"{s.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": s.deepseek_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for attempt in range(s.deepseek_max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=s.deepseek_timeout_seconds, transport=self._transport
                ) as client:
                    r = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {s.deepseek_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if r.status_code == 401:
                    raise PlanGenerationFailed("DeepSeek rejected the API key (401)")
                if r.status_code == 402:
                    raise PlanGenerationFailed("DeepSeek account has no credit (402)")
                if r.status_code != 200:
                    last_error = PlanGenerationFailed(f"HTTP {r.status_code}: {r.text[:300]}")
                else:
                    return r.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < s.deepseek_max_retries:
                continue
        raise PlanGenerationFailed(f"DeepSeek call failed: {type(last_error).__name__}: {last_error}")

    async def plan(self, requirement: dict[str, Any], tools: list[ToolSpec]) -> dict[str, Any]:
        allowed = {t.key for t in tools}
        tool_lines = "\n".join(f"- {t.key}（{t.name}，{t.side_effect_level}）" for t in tools)
        user = (
            f"教师需求：{json.dumps(requirement, ensure_ascii=False)}\n\n"
            f"可用工具：\n{tool_lines}\n\n"
            "请输出步骤图 JSON。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

        raw = await self._complete(messages)
        try:
            content = json.loads(raw)
            validate_plan(content, allowed)
            return content
        except (json.JSONDecodeError, PlanGenerationFailed) as exc:
            # one retry, with the validator's own complaint — not a generic "try again"
            messages += [
                {"role": "assistant", "content": raw[:2000]},
                {
                    "role": "user",
                    "content": f"上面的方案未通过校验：{exc}。请修正后重新输出 JSON。",
                },
            ]
            raw2 = await self._complete(messages)
            try:
                content = json.loads(raw2)
            except json.JSONDecodeError as exc2:
                raise PlanGenerationFailed(f"model did not return JSON after retry: {exc2}") from exc2
            validate_plan(content, allowed)
            return content


def build(name: str | None = None) -> Planner:
    """Pick an implementation. `template` needs no network; `deepseek` needs a key."""
    choice = (name or config.load().planner or "template").strip().lower()
    if choice == "deepseek":
        return DeepSeekPlanner()
    return TemplatePlanner()
