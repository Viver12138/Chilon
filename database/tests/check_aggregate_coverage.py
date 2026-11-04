"""Prove every contract aggregate has a physical table.

This is the check that would have caught a K011 designed from memory: if an
aggregate in the frozen state machines cannot be mapped to a table, the contracts
are not implementable as designed.

Usage:
    python database/tests/check_aggregate_coverage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    schema = json.loads((ROOT / "database/registry/schema.json").read_text(encoding="utf-8"))
    machines = json.loads((ROOT / "schemas/state_machines.v1.json").read_text(encoding="utf-8"))
    actions = json.loads((ROOT / "schemas/actions.v1.json").read_text(encoding="utf-8"))

    mapping = schema.get("aggregate_tables", {})
    tables = {t["name"] for t in schema["tables"]}

    aggregates = {a["id"] for a in machines["aggregates"]}
    action_aggregates = {a["aggregate"] for a in actions["aggregates"]}

    errors: list[str] = []

    missing = aggregates - set(mapping)
    if missing:
        errors.append(f"aggregates without a table mapping: {sorted(missing)}")

    unmapped_actions = action_aggregates - set(mapping)
    if unmapped_actions:
        errors.append(f"action aggregates without a table mapping: {sorted(unmapped_actions)}")

    for aggregate, table in mapping.items():
        if table not in tables:
            errors.append(f"aggregate {aggregate!r} maps to unknown table {table!r}")

    extra = set(mapping) - aggregates - action_aggregates
    if extra:
        errors.append(f"mapping entries with no contract aggregate: {sorted(extra)}")

    print(f"contract aggregates : {len(aggregates)}")
    print(f"mapped tables       : {len(set(mapping.values()))}")
    print(f"registry tables     : {len(tables)}")
    for aggregate in sorted(aggregates):
        print(f"  {aggregate:<22} -> {mapping.get(aggregate, 'MISSING')}")

    if errors:
        print()
        for e in errors:
            print(f"  - {e}")
        return 1
    print()
    print("OK: every aggregate maps to a table that exists in the registry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
