"""Agent turn tests: template planner offline, DeepSeek when a key is present.

The important assertions are about refusal, not generation:

* a vague requirement must not produce a plan
* a plan naming a tool the teacher lacks must not be persisted
* a failed model turn must leave the task in a state that says so

Generation is only worth testing once those hold, because a system that produces
plausible plans it cannot execute is worse than one that produces none.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import settings as config  # noqa: E402
from app.db import session as db  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402
from app.main import app  # noqa: E402
from app.services import agent, identity, planner  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


TOOLS = [
    ("knowledge.search", "知识库检索", "read"),
    ("content.generate", "内容生成", "write"),
    ("quality.check", "质量检查", "read"),
]


async def make_user() -> str:
    username = f"agent_{uuid.uuid4().hex[:10]}"
    async with db.system_session() as s:
        user_id = await identity.register(s, username, "pw12345678")
        session = await identity.login(s, username, "pw12345678")
    # Grants are owner-scoped, so they need that owner's context — which does not
    # exist until the user does. Hence two blocks rather than one merged block.
    async with db.session_for(user_id) as s:
        for key, name, side in TOOLS:
            tool_id = uuid.uuid4()
            await s.execute(
                text(
                    """
                    INSERT INTO agent_tool_definitions
                        (id, key, version, name, side_effect_level)
                    VALUES (:id, :key, '1.0.0', :name, :side)
                    ON CONFLICT (key, version) DO NOTHING
                    """
                ),
                {"id": tool_id, "key": key, "name": name, "side": side},
            )
            await s.execute(
                text(
                    """
                    INSERT INTO agent_tool_grants (id, owner_id, tool_definition_id, capability)
                    SELECT gen_random_uuid(), :o, d.id, 'invoke'
                    FROM agent_tool_definitions d
                    WHERE d.key = :key AND d.version = '1.0.0'
                    ON CONFLICT (owner_id, tool_definition_id) DO NOTHING
                    """
                ),
                {"o": user_id, "key": key},
            )
    return session.token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def scenario_extraction() -> None:
    print("1. requirement extraction refuses to invent what was not said")
    r = agent.extract_requirement("用高考题和模拟题出 12 道三角函数题")
    check("gaokao_paper" in r.sources and "mock_exam" in r.sources, f"sources detected: {r.sources}")
    check(r.question_count == 12, f"count parsed (got {r.question_count})")
    check("三角函数" in r.topic, f"topic kept: {r.topic!r}")

    r2 = agent.extract_requirement("出一道三角函数的题")
    check(r2.question_count is None, "no count stays None instead of being guessed")

    for bad in ("", "   "):
        try:
            agent.extract_requirement(bad)
            check(False, f"empty requirement accepted: {bad!r}")
        except agent.RequirementIncomplete:
            check(True, f"empty requirement refused: {bad!r}")


async def scenario_validation() -> None:
    print("2. a plan naming an unavailable tool is rejected")
    allowed = {"knowledge.search", "content.generate"}
    bad = {
        "steps": [
            {"key": "s", "type": "knowledge.search"},
            {"key": "g", "type": "content.generate", "depends_on": ["s"]},
            {"key": "x", "type": "quality.check", "depends_on": ["g"]},
        ]
    }
    try:
        planner.validate_plan(bad, allowed)
        check(False, "a plan using an ungranted tool was accepted")
    except planner.PlanGenerationFailed as exc:
        check("quality.check" in str(exc), f"refusal names the missing tool ({exc})")

    cyclic = {
        "steps": [
            {"key": "a", "type": "knowledge.search", "depends_on": ["b"]},
            {"key": "b", "type": "content.generate", "depends_on": ["a"]},
        ]
    }
    try:
        planner.validate_plan(cyclic, allowed)
        check(False, "a cyclic plan was accepted")
    except planner.PlanGenerationFailed as exc:
        check("cycle" in str(exc), "cycle is reported by the DAG validator")

    good = {"steps": [{"key": "s", "type": "knowledge.search"}]}
    check(len(planner.validate_plan(good, allowed)) == 1, "a valid minimal plan passes")


async def scenario_template_flow(client: httpx.AsyncClient) -> None:
    print("3. the agent turn produces an approvable plan (template planner)")
    token = await make_user()

    r = await client.post(
        "/tasks", headers=auth(token), json={"title": "三角函数一轮复习"}
    )
    task_id = r.json()["id"]

    r = await client.post(
        f"/tasks/{task_id}/agent/plan",
        headers=auth(token),
        json={"requirement": "用高考题和模拟题出 12 道三角函数题", "engine": "template"},
    )
    check(r.status_code == 200, f"agent turn succeeded (got {r.status_code}: {r.text[:120]})")
    if r.status_code != 200:
        return
    body = r.json()
    check(len(body["steps"]) >= 3, f"plan has steps (got {len(body['steps'])})")
    check(body["approval_id"], "an approval request was created")
    check(all("type" in s for s in body["steps"]), "every step names a tool")

    r = await client.get(f"/tasks/{task_id}", headers=auth(token))
    check(
        r.json()["status"] == "awaiting_plan_approval",
        f"task awaits approval (got {r.json()['status']})",
    )

    r = await client.get(f"/tasks/{task_id}/plan", headers=auth(token))
    check(r.status_code == 200, "the plan is readable over HTTP")

    # 12 questions → split generation, so the DAG has a join
    keys = [s["key"] for s in body["steps"]]
    check("generate-a" in keys and "generate-b" in keys, "a large set is split into parallel steps")


async def scenario_vague(client: httpx.AsyncClient) -> None:
    print("4. a vague requirement stops the turn before anything is written")
    token = await make_user()
    r = await client.post("/tasks", headers=auth(token), json={"title": "空需求"})
    task_id = r.json()["id"]

    r = await client.post(
        f"/tasks/{task_id}/agent/plan",
        headers=auth(token),
        json={"requirement": "   ", "engine": "template"},
    )
    check(r.status_code == 422, f"blank requirement rejected (got {r.status_code})")

    r = await client.get(f"/tasks/{task_id}", headers=auth(token))
    check(r.json()["status"] == "draft", f"task stayed draft (got {r.json()['status']})")


async def scenario_deepseek() -> None:
    print("5. DeepSeek planner, when a key is configured")
    s = config.load()
    if not s.llm_configured:
        print("    skip  CHILON_DEEPSEEK_API_KEY is not set")
        return

    engine = planner.DeepSeekPlanner()
    tools = [planner.ToolSpec(k, n, side) for k, n, side in TOOLS]
    requirement = {
        "topic": "三角函数",
        "sources": ["gaokao_paper", "mock_exam"],
        "question_count": 6,
        "raw_text": "用高考题和模拟题出 6 道三角函数题",
    }
    content = await engine.plan(requirement, tools)
    check(isinstance(content.get("steps"), list) and content["steps"], "model returned steps")

    specs = planner.validate_plan(content, {t.key for t in tools})
    check(len(specs) >= 2, f"plan validates with {len(specs)} steps")
    for sp in specs:
        check(sp.step_type in {t.key for t in tools}, f"step {sp.key!r} uses a real tool ({sp.step_type})")
    print(f"    info  model plan: {[(s.key, s.step_type) for s in specs]}")


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        await scenario_extraction()
        await scenario_validation()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await scenario_template_flow(client)
            await scenario_vague(client)

        await scenario_deepseek()
    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: the agent turn plans, validates, and refuses what it cannot execute")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
