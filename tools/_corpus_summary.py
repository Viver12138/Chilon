"""Summarise the built corpus: sources, questions, chunks, answers, and a few queries."""

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

QUERIES = ["补集", "导数", "等差数列 求和", "函数的单调性"]


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
        return 2
    db.init(await provision_runtime_role(url))
    try:
        async with db.system_session() as session:
            stats = (
                await session.execute(
                    text(
                        """
                        SELECT (SELECT count(*) FROM knowledge_sources WHERE scope='platform') AS sources,
                               (SELECT count(*) FROM knowledge_questions q
                                  JOIN knowledge_document_versions v ON v.id=q.document_version_id
                                  JOIN knowledge_sources s ON s.id=v.source_id
                                 WHERE s.scope='platform') AS questions,
                               (SELECT count(*) FROM knowledge_chunks c
                                  JOIN knowledge_document_versions v ON v.id=c.document_version_id
                                  JOIN knowledge_sources s ON s.id=v.source_id
                                 WHERE s.scope='platform') AS chunks,
                               (SELECT count(*) FROM knowledge_questions q
                                  JOIN knowledge_document_versions v ON v.id=q.document_version_id
                                  JOIN knowledge_sources s ON s.id=v.source_id
                                 WHERE s.scope='platform' AND q.answer_locator IS NOT NULL) AS answered
                        """
                    )
                )
            ).one()
            print(
                f"sources={stats.sources} questions={stats.questions} "
                f"chunks={stats.chunks} answered={stats.answered}"
            )
            by_type = (
                await session.execute(
                    text(
                        """
                        SELECT s.source_type, count(DISTINCT s.id) AS n,
                               count(c.id) AS chunks
                        FROM knowledge_sources s
                        JOIN knowledge_document_versions v ON v.source_id = s.id
                        LEFT JOIN knowledge_chunks c ON c.document_version_id = v.id
                        WHERE s.scope = 'platform'
                        GROUP BY s.source_type
                        """
                    )
                )
            ).all()
            for row in by_type:
                print(f"  {row.source_type:12} sources={row.n:4} chunks={row.chunks}")

            teacher = await identity.register(session, f"sum_{uuid.uuid4().hex[:6]}", "sum_password_1")

        for topic in QUERIES:
            async with db.session_for(teacher) as session:
                result = await tools_impl.knowledge_search(session, ctx(teacher, topic))
            hits = result["hits"]
            print(f"\n「{topic}」 -> {len(hits)} 命中")
            for hit in hits[:2]:
                title = (hit.get("source_title") or "?")[:30]
                excerpt = (hit.get("excerpt") or "")[:80].replace("\n", " ")
                print(f"    - {title} | {excerpt}")
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
