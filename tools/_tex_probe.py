"""Measure the imported TeX corpus and ask a few teacher-style questions."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import identity  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

QUERIES = ["导数", "圆锥曲线", "数列 求和"]


def ctx(owner, topic):
    return tools_impl.ToolContext(
        owner_id=owner,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement={"topic": topic, "sources": []},
        deps={},
    )


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2
    db.init(await provision_runtime_role(url))
    try:
        async with db.system_session() as session:
            stats = (
                await session.execute(
                    text(
                        """
                        SELECT (SELECT count(*) FROM knowledge_sources WHERE scope = 'platform') AS sources,
                               (SELECT count(*) FROM knowledge_questions q
                                  JOIN knowledge_document_versions v ON v.id = q.document_version_id
                                  JOIN knowledge_sources s ON s.id = v.source_id
                                 WHERE s.scope = 'platform') AS questions,
                               (SELECT count(*) FROM knowledge_chunks c
                                  JOIN knowledge_document_versions v ON v.id = c.document_version_id
                                  JOIN knowledge_sources s ON s.id = v.source_id
                                 WHERE s.scope = 'platform') AS chunks,
                               (SELECT count(*) FROM knowledge_questions q
                                  JOIN knowledge_document_versions v ON v.id = q.document_version_id
                                  JOIN knowledge_sources s ON s.id = v.source_id
                                 WHERE s.scope = 'platform' AND q.answer_locator IS NOT NULL) AS answered
                        """
                    )
                )
            ).one()
            print(
                f"corpus: sources={stats.sources} questions={stats.questions} "
                f"chunks={stats.chunks} answered={stats.answered}"
                f" ({stats.answered / max(stats.questions, 1):.0%})"
            )
            top = (
                await session.execute(
                    text(
                        """
                        SELECT s.title, count(q.id) AS n
                        FROM knowledge_sources s
                        JOIN knowledge_document_versions v ON v.source_id = s.id
                        LEFT JOIN knowledge_questions q ON q.document_version_id = v.id
                        WHERE s.scope = 'platform'
                        GROUP BY s.title ORDER BY n DESC LIMIT 3
                        """
                    )
                )
            ).all()
            for row in top:
                print(f"  {row.title}  {row.n} 题")

            teacher_name = f"tex_{uuid.uuid4().hex[:6]}"
            teacher = await identity.register(session, teacher_name, "tex_password_1")

        for topic in QUERIES:
            async with db.session_for(teacher) as session:
                result = await tools_impl.knowledge_search(session, ctx(teacher, topic))
            hits = result["hits"]
            print(f"\n「{topic}」 -> {len(hits)} 命中")
            for hit in hits[:3]:
                title = hit.get("source_title") or "?"
                excerpt = (hit.get("excerpt") or "").replace("\n", " ")[:70]
                print(f"    - {title} | {excerpt}")
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
