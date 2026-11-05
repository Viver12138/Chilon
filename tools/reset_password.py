"""Operator password reset.

There is no email channel, so password recovery is an administrative act: whoever can
already reach the database can restore an account. This script exists so that act is
explicit and auditable instead of being "delete the container and lose everything".

    CHILON_DATABASE_URL=... python tools/reset_password.py --username teacher_demo

Prints the new password once. It is not stored anywhere in readable form afterwards —
only its scrypt hash.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402

from app.db import session as db  # noqa: E402
from app.services import passwords  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a Chilon account password")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default=None, help="omit to generate one")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CHILON_DATABASE_URL"),
        help="defaults to CHILON_DATABASE_URL",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("CHILON_DATABASE_URL is not set (or pass --database-url)", file=sys.stderr)
        return 2

    db.init(args.database_url)
    try:
        # the reset is an administrative write: it runs without a tenant context,
        # exactly like a migration, and is not subject to the teacher's policies
        async with db.system_session() as session:
            password, note = await passwords.reset_for_username(
                session, args.username, args.password
            )
    except passwords.ResetNotAllowed as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    finally:
        await db.dispose()

    print(f"username: {args.username}")
    print(f"password: {password}")
    print(note)
    print("Store it now; only the hash is kept.")
    _ = psycopg
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
