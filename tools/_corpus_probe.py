"""Ask three teacher-style questions against the imported corpus."""

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

QUERIES = [
    "集合",
    "导数与函数单调性",
    "出一道关于三角函数的单选题",
]


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
                        SELECT count(*) FILTER (WHERE scope = 'platform') AS platform_sources,
                               (SELECT count(*) FROM knowledge_document_versions v
                                JOIN knowledge_sources s ON s.id = v.source_id
                                WHERE s.scope = 'platform') AS platform_versions,
                               (SELECT count(*) FROM knowledge_questions q
                                JOIN knowledge_document_versions v ON v.id = q.document_version_id
                                JOIN knowledge_sources s ON s.id = v.source_id
                                WHERE s.scope = 'platform') AS platform_questions,
                               (SELECT count(*) FROM knowledge_chunks c
                                JOIN knowledge_document_versions v ON v.id = c.document_version_id
                                JOIN knowledge_sources s ON s.id = v.source_id
                                WHERE s.scope = 'platform') AS platform_chunks
                        FROM knowledge_sources
                        """
                    )
                )
            ).one()
            print(
                f"corpus: sources={stats.platform_sources} versions={stats.platform_versions} "
                f"questions={stats.platform_questions} chunks={stats.platform_chunks}"
            )
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT s.title, v.lifecycle_status,
                               (SELECT count(*) FROM knowledge_questions q
                                WHERE q.document_version_id = v.id) AS questions
                        FROM knowledge_sources s
                        JOIN knowledge_document_versions v ON v.source_id = s.id
                        WHERE s.scope = 'platform'
                        ORDER BY s.title
                        """
                    )
                )
            ).all()
            for row in rows:
                print(f"  {row.title:44} {row.lifecycle_status:14} {row.questions} 题")

            teacher_name = f"corpus_{uuid.uuid4().hex[:6]}"
            teacher = await identity.register(session, teacher_name, "corpus_password_1")

        print()
        for topic in QUERIES:
            async with db.session_for(teacher) as session:
                result = await tools_impl.knowledge_search(session, ctx(teacher, topic))
            hits = result["hits"]
            print(f"「{topic}」 -> {len(hits)} 命中")
            for hit in hits[:3]:
                title = hit.get("source_title") or hit.get("title") or "?"
                excerpt = (hit.get("excerpt") or "").replace("\n", " ")[:70]
                print(f"    - {title} | {excerpt}")
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
