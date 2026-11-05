"""Show what a textbook import actually produced, and ask a teacher-style question."""

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
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT s.title, s.rights_status, count(c.id) AS chunks,
                               min(c.ordinal) AS first_ord, max(c.ordinal) AS last_ord
                        FROM knowledge_sources s
                        JOIN knowledge_document_versions v ON v.source_id = s.id
                        LEFT JOIN knowledge_chunks c ON c.document_version_id = v.id
                        WHERE s.scope = 'platform'
                        GROUP BY s.title, s.rights_status
                        ORDER BY s.title
                        """
                    )
                )
            ).all()
            for row in rows:
                print(f"{row.title[:34]:36} {row.rights_status:10} chunks={row.chunks:4}")
            sample = (
                await session.execute(
                    text(
                        """
                        SELECT c.ordinal, c.text_content FROM knowledge_chunks c
                        JOIN knowledge_document_versions v ON v.id = c.document_version_id
                        JOIN knowledge_sources s ON s.id = v.source_id
                        WHERE s.scope = 'platform' AND s.source_type = 'textbook'
                        ORDER BY c.ordinal LIMIT 3
                        """
                    )
                )
            ).all()
            for row in sample:
                body = (row.text_content or "").replace("\n", " ")
                print(f"\n  chunk {row.ordinal}: {body[:220]}")

            teacher = await identity.register(session, f"tb_{uuid.uuid4().hex[:6]}", "tb_password_1")

        async with db.session_for(teacher) as session:
            result = await tools_impl.knowledge_search(session, ctx(teacher, "补集"))
        hits = result["hits"]
        print(f"\n「补集」 -> {len(hits)} 命中")
        for hit in hits[:3]:
            print("   -", (hit.get("source_title") or "?"), "|", (hit.get("excerpt") or "")[:90].replace("\n", " "))
    finally:
        await db.dispose()
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
