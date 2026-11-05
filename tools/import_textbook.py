"""Import 人教 A 版 textbooks (OCR, one call per page).

    python tools/import_textbook.py --dir corpus/textbooks --max-pages 12   # pilot
    python tools/import_textbook.py --dir corpus/textbooks                  # all 974 pages

Requires an admin database role and CHILON_OCR_PROVIDER=aliyun. Every page is one
billed call, so `--max-pages` exists to check quality before spending the full amount.
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
from app.services import textbook_import  # noqa: E402


async def is_admin(session) -> bool:
    return bool(
        (
            await session.execute(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar()
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import textbooks by OCR")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--file", help="a single PDF instead of the whole directory")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="OCR at most N pages per book (0 = all). Use it to pilot before paying",
    )
    parser.add_argument("--database-url", default=os.environ.get("CHILON_DATABASE_URL"))
    args = parser.parse_args()

    folder = Path(args.dir)
    targets = [Path(args.file)] if args.file else sorted(folder.glob("*.pdf"))
    if not targets:
        print("no PDFs to import", file=sys.stderr)
        return 1
    if not args.database_url:
        print("CHILON_DATABASE_URL is not set", file=sys.stderr)
        return 2

    db.init(args.database_url)
    imported = skipped = failed = 0
    pages = chunks = 0
    try:
        async with db.system_session() as session:
            if not await is_admin(session):
                print("refusing: platform rows need a role that bypasses RLS", file=sys.stderr)
                return 2
        for path in targets:
            try:
                async with db.system_session() as session:
                    result = await textbook_import.import_textbook(
                        session,
                        path=path,
                        title=path.stem,
                        max_pages=args.max_pages,
                    )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {path.name}: {exc}", file=sys.stderr)
                continue
            if result["skipped"]:
                skipped += 1
                print(f"skip {path.name}")
                continue
            imported += 1
            pages += result["pages"]
            chunks += result["chunks"]
            print(f"ok   {path.name}: {result['pages']} 页, {result['chunks']} 块")
    finally:
        await db.dispose()

    print(f"\nimported={imported} skipped={skipped} failed={failed} pages={pages} chunks={chunks}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
