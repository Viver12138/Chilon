"""Every table must have at least one RLS policy.

Under `FORCE ROW LEVEL SECURITY` a table with no policy denies everyone except a
superuser. That failure mode is invisible until the app stops running as a superuser,
and it has already cost five separate debugging rounds.

This check is a ratchet: it does not care that the policies are good (other checks do
that), only that none is missing. A new table added to the registry without a policy
fails here instead of in production.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ROOT / "database" / "registry" / "fields"


def main() -> int:
    total = 0
    missing: list[tuple[str, str]] = []
    owner_without_rule: list[str] = []
    service_scoped: list[str] = []

    for path in sorted(FIELDS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for table in payload["tables"]:
            total += 1
            name = table["name"]
            policies = table.get("policies") or []
            if not policies:
                missing.append((path.name, name))
                continue
            has_owner = "owner_id" in {f["name"] for f in table["fields"]}
            is_service = any(p.get("using") == "true" for p in policies)
            if has_owner and not any("app_current_user_id" in (p.get("using") or "") for p in policies):
                owner_without_rule.append(name)
            if is_service:
                service_scoped.append(name)

    print(f"tables                  : {total}")
    print(f"tables without a policy : {len(missing)}")
    print(f"service-scoped tables   : {len(service_scoped)}")

    failed = False
    if missing:
        failed = True
        print("\nFAIL: these tables have no policy (deny-all under FORCE RLS):")
        for module, name in missing:
            print(f"  {module:10} {name}")

    if owner_without_rule:
        failed = True
        print("\nFAIL: owner-scoped tables with no owner predicate:")
        for name in owner_without_rule:
            print(f"  {name}")

    if failed:
        return 1

    print("\nOK: every table has a policy, and every owner-scoped table is owner-scoped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
