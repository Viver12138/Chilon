"""Fail when the latest migration no longer matches the generated DDL.

The migration workflow is: change registry -> regenerate DDL -> generate a new
revision. This check catches the case where the first two happened but the third
was forgotten, which would leave the database schema behind the contracts.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VERSIONS = ROOT / "backend" / "migrations" / "versions"
MANIFEST = ROOT / "database" / "generated" / "manifest.json"

PATTERN = re.compile(r'^revision = "([^"]+)"', re.M)
HASH = re.compile(r'^SCHEMA_HASH = "([0-9a-f]{64})"', re.M)


def main() -> int:
    if not VERSIONS.exists():
        print(f"no migrations directory at {VERSIONS.relative_to(ROOT)}")
        return 1
    revisions = sorted(VERSIONS.glob("*.py"))
    if not revisions:
        print("no migration revisions found")
        return 1

    latest = revisions[-1]
    text = latest.read_text(encoding="utf-8")
    m_hash = HASH.search(text)
    if not m_hash:
        print(f"{latest.name}: SCHEMA_HASH missing")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if m_hash.group(1) != manifest["schema_hash"]:
        print("DRIFT: the generated DDL changed but no new migration was created")
        print(f"  latest revision {latest.name} records {m_hash.group(1)[:12]}")
        print(f"  current manifest         {''.join(manifest['schema_hash'][:12])}")
        print("  fix: python database/generator/gen_migration.py --id <new> --down " + (PATTERN.search(text).group(1) if PATTERN.search(text) else "?"))
        return 1

    print(f"OK: latest migration {latest.name} matches the generated DDL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
