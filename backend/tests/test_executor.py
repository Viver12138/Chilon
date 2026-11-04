"""End-to-end: one sentence becomes questions, with citations and a check report.

This is the first test where the system produces teaching content rather than
plumbing. It runs the offline generator by default so CI needs no network; the
DeepSeek variant is exercised locally when a key is present.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app import settings as config  # noqa: E402
from app.db import session as db  # noqa: E402
from app.services import agent, executor, executions, planner, plans, tasks  # noqa: E402

FAILURES: list[str] = []


def mark(stage: str) -> None:
    """Emit a GitHub annotation so a hang is locatable without job logs.

    Public repository job logs need admin rights to read; annotations do not. This
    prints a plain line locally and an annotation in CI.
    """
    if os.environ.get("CI"):
        print(f"::notice::executor test: {stage}", flush=True)
    else:
        print(f"[stage] {stage}", flush=True)


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


async def seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    """A teacher, three tools, and a tiny platform knowledge base."""
    user_id = uuid.uuid4()
    username = f"exec_{user_id.hex[:10]}"
    await session.execute(
        text("INSERT INTO users (id, username, display_name) VALUES (:id, :u, :u)"),
        {"id": user_id, "u": username},
    )

    for key, name, side in TOOLS:
        await session.execute(
            text(
                """
                INSERT INTO agent_tool_definitions (id, key, version, name, side_effect_level)
                VALUES (:id, :key, '1.0.0', :name, :side)
                ON CONFLICT (key, version) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "key": key, "name": name, "side": side},
        )
        await session.execute(
            text(
                """
                INSERT INTO agent_tool_grants (id, owner_id, tool_definition_id, capability)
                SELECT gen_random_uuid(), :o, d.id, 'invoke'
                FROM agent_tool_definitions d WHERE d.key = :key AND d.version = '1.0.0'
                ON CONFLICT (owner_id, tool_definition_id) DO NOTHING
                """
            ),
            {"o": user_id, "key": key},
        )

    category_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_categories (id, scope, owner_id, key, name, source_type, is_system)
            VALUES (:id, 'platform', NULL, :key, '高考题', 'gaokao_paper', true)
            """
        ),
        {"id": category_id, "key": f"gk_{uuid.uuid4().hex[:6]}"},
    )
    source_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by)
            VALUES (:id, 'platform', NULL, :cat, 'gaokao_paper', '2023 全国甲卷 数学',
                    'licensed', 'classroom', :owner)
            """
        ),
        {"id": source_id, "cat": category_id, "owner": user_id},
    )
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by)
            VALUES (:id, :src, 1, :key, :hash, 'application/pdf', 1024, 'approved', :owner)
            """
        ),
        {
            "id": version_id,
            "src": source_id,
            "key": f"kb/{uuid.uuid4().hex}.pdf",
            "hash": "a" * 64,
            "owner": user_id,
        },
    )
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_chunks
                (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                 locator, content_kind, parser_version, parse_schema_version)
            VALUES (:id, :dv, :key, 1, :body, :hash, CAST(:loc AS jsonb), 'text', 'p1', '1.0')
            """
        ),
        {
            "id": chunk_id,
            "dv": version_id,
            "key": f"c_{uuid.uuid4().hex[:6]}",
            "body": "已知三角函数 f(x)=sin(2x+π/3)，求其最小正周期与单调递增区间。",
            "hash": "b" * 64,
            "loc": '{"page_number": 3, "char_start": 0, "char_end": 40}',
        },
    )
    return user_id, chunk_id


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(url)
    try:
        async with db.system_session() as s:
            user_id, chunk_id = await seed(s)

        mark("start")
        print("1. the agent plans, the teacher approves, the executor produces content")
        async with db.session_for(user_id) as s:
            task = await tasks.create_task(s, user_id, "三角函数一轮复习")

        async with db.session_for(user_id) as s:
            proposal = await agent.propose_plan(
                s,
                user_id,
                task.id,
                "用高考题出 4 道三角函数题",
                plan_engine=planner.TemplatePlanner(),
            )
        check(len(proposal["steps"]) >= 3, f"plan has {len(proposal['steps'])} steps")

        async with db.session_for(user_id) as s:
            approved = await agent.approve_plan(
                s, user_id, task.id, uuid.UUID(proposal["approval_id"])
            )
        check(approved["task_status"] == "ready", f"task ready after approval (got {approved['task_status']})")

        async with db.session_for(user_id) as s:
            current = await tasks.get_task(s, task.id)
        async with db.session_for(user_id) as s:
            execution_id = await executions.start_execution(
                s,
                user_id,
                task.id,
                uuid.UUID(proposal["plan_version_id"]),
                uuid.UUID(proposal["approval_id"]),
                expected_task_state_version=current.state_version,
            )

        async with db.session_for(user_id) as s:
            result = await executor.run_once(s, user_id, execution_id)

        check(result["failed_steps"] == [], f"no step failed (got {result['failed_steps']})")
        check(result["outcome"] == "succeeded", f"execution succeeded (got {result['outcome']})")
        check(len(result["processed"]) >= 3, f"{len(result['processed'])} steps executed")

        mark("1 planned and executed")
        print("2. the step outputs actually contain teaching content")
        async with db.session_for(user_id) as s:
            outputs = (
                await s.execute(
                    text(
                        """
                        SELECT st.step_key, se.output
                        FROM agent_step_executions se
                        JOIN agent_plan_steps st ON st.id = se.plan_step_id
                        WHERE se.execution_id = :e ORDER BY st.ordinal
                        """
                    ),
                    {"e": execution_id},
                )
            ).all()
        by_key = {r.step_key: r.output for r in outputs}

        search_out = next((v for v in by_key.values() if v and "hits" in v), None)
        check(search_out is not None and search_out["hit_count"] >= 1, "retrieval found the seeded passage")

        gen_out = next((v for v in by_key.values() if v and "questions" in v), None)
        check(gen_out is not None and len(gen_out["questions"]) == 4, f"4 questions produced")
        check(
            all(q["answer"] for q in gen_out["questions"]),
            "every question carries an answer (teacher version needs it)",
        )

        check_out = next((v for v in by_key.values() if v and "verdict" in v), None)
        check(check_out is not None, "quality report produced")
        check(
            check_out["citations_available"] >= 1,
            f"the checker saw {check_out['citations_available']} usable citation(s)",
        )
        check(
            "not_checked" in check_out and check_out["not_checked"],
            "the report states what it did NOT check",
        )

        mark("2 outputs inspected")
        print("3. tool calls were recorded with results and hashes")
        async with db.session_for(user_id) as s:
            tool_rows = (
                await s.execute(
                    text(
                        """
                        SELECT d.key, e.status, e.result_hash
                        FROM agent_tool_executions e
                        JOIN agent_tool_definitions d ON d.id = e.tool_definition_id
                        WHERE e.execution_id = :x
                        """
                    ),
                    {"x": execution_id},
                )
            ).all()
        check(len(tool_rows) == 3, f"3 tool invocations recorded (got {len(tool_rows)})")
        check(all(r.status == "succeeded" for r in tool_rows), "all tool invocations succeeded")
        check(all(r.result_hash for r in tool_rows), "every invocation stored a result hash")

        mark("3 tool calls inspected")
        print("4. re-running the executor does not redo work")
        async with db.session_for(user_id) as s:
            again = await executor.run_once(s, user_id, execution_id)
        check(
            again["processed"] == [] and again["outcome"] == "succeeded",
            "a second run finds nothing to do and keeps the settled outcome",
        )

        mark("4 rerun checked")
        print("5. DeepSeek generation, when configured")
        if not config.load().llm_configured:
            print("    skip  CHILON_DEEPSEEK_API_KEY is not set")
        else:
            from app.tools import impl as tool_impl

            ctx = tool_impl.ToolContext(
                owner_id=user_id,
                execution_id=execution_id,
                step_key="gen-live",
                spec={"engine": "deepseek", "count": 2},
                requirement={"topic": "三角函数", "question_count": 2},
                deps={"search": search_out},
            )
            async with db.session_for(user_id) as s:
                live = await tool_impl.content_generate(s, ctx)
            check(live["generator"] == "deepseek", "live generator used the model")
            check(len(live["questions"]) == 2, f"model produced {len(live['questions'])} questions")
            for q in live["questions"]:
                check(bool(q["stem"]) and bool(q["answer"]), f"Q{q['no']} has stem and answer")
    finally:
        await db.dispose()

    mark("all scenarios done")
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: one sentence produced questions, citations and a check report")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
