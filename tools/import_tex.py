"""Import the LaTeX corpus (2012+) into the platform knowledge base.

    docker compose exec app python tools/import_tex.py --content /corpus/tex/content --since 2012

Requires an admin database role: platform rows are written where RLS is bypassed.
Idempotent by file checksum, so re-running is safe.
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
from app.services import tex_import  # noqa: E402


async def is_admin(session) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).scalar()
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import TeX papers into the platform corpus")
    parser.add_argument("--content", required=True, help="the corpus content/ directory")
    parser.add_argument("--since", type=int, default=2012)
    parser.add_argument("--limit", type=int, default=0, help="import at most N papers (0 = all)")
    parser.add_argument("--type", dest="source_type", default="gaokao_paper")
    parser.add_argument("--database-url", default=os.environ.get("CHILON_DATABASE_URL"))
    args = parser.parse_args()

    content = Path(args.content)
    if not content.is_dir():
        print(f"not a directory: {content}", file=sys.stderr)
        return 2
    if not args.database_url:
        print("CHILON_DATABASE_URL is not set", file=sys.stderr)
        return 2

    files = [
        path
        for year in sorted(content.iterdir())
        if year.is_dir() and year.name.isdigit() and int(year.name) >= args.since
        for path in sorted(year.glob("*.tex"))
    ]
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("no .tex files found", file=sys.stderr)
        return 1

    db.init(args.database_url)
    imported = skipped = failed = 0
    problems = answered = 0
    try:
        async with db.system_session() as session:
            if not await is_admin(session):
                print(
                    "refusing to run: platform rows need a role that bypasses RLS",
                    file=sys.stderr,
                )
                return 2

        for index, path in enumerate(files, 1):
            try:
                async with db.system_session() as session:
                    result = await tex_import.import_paper(
                        session, path=path, base=content, source_type=args.source_type
                    )
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
                failed += 1
                print(f"FAIL {path.parent.name}/{path.name}: {exc}", file=sys.stderr)
                continue
            if result["skipped"]:
                skipped += 1
                continue
            if result.get("error"):
                failed += 1
                print(f"FAIL {path.name}: {result['error']}", file=sys.stderr)
                continue
            imported += 1
            problems += result["problems"]
            answered += result["answered"]
            if index % 25 == 0 or index == len(files):
                print(
                    f"  {index}/{len(files)} papers, {problems} problems, {answered} answers"
                )
    finally:
        await db.dispose()

    print(
        f"\nimported={imported} skipped={skipped} failed={failed} "
        f"problems={problems} answered={answered}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
