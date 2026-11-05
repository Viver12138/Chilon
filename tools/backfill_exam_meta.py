"""Backfill exam_year / exam_paper on existing platform sources, and wire it into imports.

The columns are the only reason "2024 新高考Ⅰ卷" can be a query at all: without them the
year lives in a free-text title and no amount of retrieval work can filter on it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services.exam_meta import parse_exam_meta  # noqa: E402

URL = "postgresql+psycopg://postgres:chilon_test_only@localhost:55495/chilon"


async def main() -> int:
    db.init(URL)
    updated = skipped = 0
    try:
        async with db.system_session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, title, source_type FROM knowledge_sources "
                        "WHERE scope = 'platform'"
                    )
                )
            ).all()
            for row in rows:
                year, paper = parse_exam_meta(row.title)
                if year is None and paper is None:
                    skipped += 1
                    continue
                await session.execute(
                    text(
                        "UPDATE knowledge_sources SET year = :year, exam_paper = :paper "
                        "WHERE id = :id"
                    ),
                    {"year": year, "paper": paper, "id": row.id},
                )
                updated += 1

        async with db.system_session() as session:
            stats = (
                await session.execute(
                    text(
                        """
                        SELECT source_type,
                               count(*) AS total,
                               count(year) AS with_year,
                               count(exam_paper) AS with_paper
                        FROM knowledge_sources WHERE scope = 'platform'
                        GROUP BY source_type ORDER BY source_type
                        """
                    )
                )
            ).all()
            for row in stats:
                print(
                    f"{row.source_type:12} total={row.total:4} "
                    f"year={row.with_year:4} paper={row.with_paper:4}"
                )
    finally:
        await db.dispose()
    print(f"\nupdated={updated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
