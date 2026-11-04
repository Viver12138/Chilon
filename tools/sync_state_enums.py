"""Rewrite every aggregate status enum from the frozen state machine contract.

The registry enums for K011 were written from the master document's prose rather
than from `schemas/state_machines.v1.json`, and eight of them drifted. This makes
the contract the single source: the CHECK expression and the DEFAULT are both
derived from it.

Usage:
    python tools/sync_state_enums.py --apply
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ROOT / "database" / "registry" / "fields"


def load() -> tuple[dict, dict[str, dict]]:
    machines = json.loads((ROOT / "schemas/state_machines.v1.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "database/registry/schema.json").read_text(encoding="utf-8"))
    return machines, schema


def main() -> int:
    apply = "--apply" in sys.argv
    machines, schema = load()
    mapping = schema["aggregate_tables"]

    by_file: dict[str, dict] = {}
    for path in sorted(FIELDS.glob("*.json")):
        by_file[path.name] = json.loads(path.read_text(encoding="utf-8"))

    table_to_file = {}
    for name, payload in by_file.items():
        for table in payload["tables"]:
            table_to_file[table["name"]] = name

    changes: list[str] = []

    for agg in machines["aggregates"]:
        table_name = mapping.get(agg["id"])
        if not table_name:
            continue
        file_name = table_to_file.get(table_name)
        if not file_name:
            continue

        states: list[str] = agg["states"]
        initial = (agg.get("initial_states") or states)[0]
        status_field = (agg.get("status_field") or "status").split(".")[-1]

        table = next(t for t in by_file[file_name]["tables"] if t["name"] == table_name)

        # 1. the CHECK expression
        rewritten = False
        for con in table.get("constraints", []):
            expr = con.get("expr") or ""
            if re.search(rf"\b{status_field}\b\s+IN\s*\(", expr):
                wanted = f"{status_field} IN (" + ",".join(f"'{s}'" for s in states) + ")"
                if expr != wanted:
                    changes.append(f"{table_name}: enum {len(expr)} chars -> {len(states)} states")
                    con["expr"] = wanted
                rewritten = True
                break
        if not rewritten:
            changes.append(f"{table_name}: NO ENUM CONSTRAINT FOUND for {status_field}")

        # 2. the DEFAULT must be a legal state
        for field in table["fields"]:
            if field["name"] != status_field:
                continue
            default = field.get("default")
            if not default:
                break
            literal = default.strip().strip("'")
            if literal not in states:
                changes.append(f"{table_name}: default {literal!r} -> {initial!r}")
                field["default"] = f"'{initial}'"
            break

    for line in changes:
        print(line)
    print()
    print(f"{len(changes)} change(s)")

    if not apply:
        print("dry run; rerun with --apply")
        return 0

    for name, payload in by_file.items():
        (FIELDS / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
            newline="\n",
        )
    print("written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
