"""Import platform materials (textbooks, papers, mocks) into the shared corpus.

    export CHILON_DATABASE_URL=postgresql+psycopg://postgres:...@host:5432/chilon
    python tools/import_platform.py --dir docs/题库 --source-type gaokao_paper

Must run with an **admin** database role: platform rows are written where RLS is
bypassed, exactly like a migration. The tool refuses to run as an ordinary role rather
than failing halfway through with a policy error.

Idempotent by checksum, so re-running over the same directory is safe.
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
from app.services import platform_import  # noqa: E402

SUFFIXES = (".pdf", ".docx", ".jpg", ".jpeg", ".png")


async def is_admin(session) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).scalar()
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import platform materials")
    parser.add_argument("--file", help="one file")
    parser.add_argument("--dir", help="a directory of files")
    parser.add_argument(
        "--source-type",
        default="gaokao_paper",
        choices=("textbook", "gaokao_paper", "mock_exam", "workbook", "other"),
    )
    parser.add_argument("--title", help="title for a single file; defaults to the file name")
    parser.add_argument(
        "--no-accept",
        action="store_true",
        help="leave papers that need review in pending_review instead of accepting them",
    )
    parser.add_argument("--database-url", default=os.environ.get("CHILON_DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        print("CHILON_DATABASE_URL is not set (or pass --database-url)", file=sys.stderr)
        return 2

    if args.file:
        targets = [Path(args.file)]
    elif args.dir:
        folder = Path(args.dir)
        if not folder.is_dir():
            print(f"not a directory: {folder}", file=sys.stderr)
            return 2
        targets = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUFFIXES)
    else:
        print("pass --file or --dir", file=sys.stderr)
        return 2

    if not targets:
        print("nothing to import", file=sys.stderr)
        return 1

    db.init(args.database_url)
    imported = skipped = failed = 0
    try:
        async with db.system_session() as session:
            if not await is_admin(session):
                print(
                    "refusing to run: the current database role cannot bypass RLS, and "
                    "platform rows are admin-only by design",
                    file=sys.stderr,
                )
                return 2

        for path in targets:
            title = args.title if (args.title and len(targets) == 1) else path.stem
            try:
                async with db.system_session() as session:
                    result = await platform_import.import_document(
                        session,
                        path=path,
                        title=title,
                        source_type=args.source_type,
                        accept=not args.no_accept,
                    )
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop a batch
                failed += 1
                print(f"FAIL {path.name}: {exc}", file=sys.stderr)
                continue

            if result["skipped"]:
                skipped += 1
                print(f"skip {path.name}: {result['reason']}")
                continue
            imported += 1
            reasons = ",".join(result["review_reasons"]) or "-"
            print(
                f"ok   {path.name}: {result['questions']} 题, status={result['status']}"
                f", reasons={reasons}, promoted={result['promoted']}"
            )
    finally:
        await db.dispose()

    print(f"\nimported={imported} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
