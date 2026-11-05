"""Import OCR'd mock papers (sample first, then the rest).

    python tools/import_mock.py --dir corpus/mock-exams --limit 5

OCR is billed per page, so `--limit` exists: check the segmentation quality on a handful
before paying for 136 files.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import mock_import  # noqa: E402


async def is_admin(session) -> bool:
    return bool(
        (
            await session.execute(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar()
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import mock papers by OCR")
    parser.add_argument("--dir", default="corpus/mock-exams")
    parser.add_argument("--limit", type=int, default=5, help="0 = all")
    parser.add_argument("--database-url", default=os.environ.get("CHILON_DATABASE_URL"))
    args = parser.parse_args()

    folder = Path(args.dir)
    files = sorted(folder.glob("*试题.pdf"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("no 试题 pdf found", file=sys.stderr)
        return 1
    if not args.database_url:
        print("CHILON_DATABASE_URL is not set", file=sys.stderr)
        return 2

    db.init(args.database_url)
    try:
        async with db.system_session() as session:
            if not await is_admin(session):
                print("refusing: platform rows need a role that bypasses RLS", file=sys.stderr)
                return 2
        total_pages = total_questions = 0
        for path in files:
            try:
                async with db.system_session() as session:
                    result = await mock_import.import_mock_paper(
                        session, path=path, title=path.stem.replace("__数学试题", "")
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {path.name[:50]}: {exc}", file=sys.stderr)
                continue
            if result.get("skipped"):
                print(f"skip {path.name[:50]}")
                continue
            total_pages += result["pages"]
            total_questions += result["questions"]
            print(
                f"ok   {result['title'][:40]:42} pages={result['pages']} "
                f"questions={result['questions']} gaps={result['gaps'][:8]}"
            )
    finally:
        await db.dispose()

    print(f"\npages={total_pages} questions={total_questions}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
