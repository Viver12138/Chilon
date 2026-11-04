"""Every aggregate status enum must equal its frozen state machine states.

This exists because it already went wrong: the K011 enums were written from the
master document's prose instead of from `schemas/state_machines.v1.json`, and
eight aggregates drifted. Two of them also had a DEFAULT that was not a legal
state at all, which would have made the very first insert fail at runtime.

The contract is the input, not a reference to consult afterwards.

Usage:
    python database/tests/check_state_contract.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    machines = json.loads((ROOT / "schemas/state_machines.v1.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "database/registry/schema.json").read_text(encoding="utf-8"))
    mapping = schema["aggregate_tables"]

    tables: dict[str, dict] = {}
    for path in (ROOT / "database/registry/fields").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for table in payload["tables"]:
            tables[table["name"]] = table

    errors: list[str] = []
    checked = 0

    # A transition may declare several from-states or triggers; after expansion
    # every (state, trigger) pair must be unique, otherwise "which transition
    # fired" is ambiguous and an implementation has to guess.
    for agg in machines["aggregates"]:
        pairs: dict[tuple[str, str], list[str]] = {}
        for tr in agg["transitions"]:
            from_states = tr["from"] if isinstance(tr["from"], list) else [tr["from"]]
            triggers = tr["trigger"] if isinstance(tr["trigger"], list) else [tr["trigger"]]
            for state in from_states:
                for trigger in triggers:
                    pairs.setdefault((state, trigger), []).append(tr["id"])
        duplicates = {k: v for k, v in pairs.items() if len(v) > 1}
        for (state, trigger), ids in sorted(duplicates.items()):
            errors.append(
                f"{agg['id']}: duplicate edge ({state!r}, {trigger!r}) declared by {ids}"
            )

    for agg in machines["aggregates"]:
        table_name = mapping.get(agg["id"])
        table = tables.get(table_name)
        if not table:
            errors.append(f"{agg['id']}: mapped table {table_name!r} not found in the registry")
            continue

        field_name = (agg.get("status_field") or "status").split(".")[-1]
        states = agg["states"]

        enum_values = None
        enum_expr = None
        for con in table.get("constraints", []):
            expr = con.get("expr") or ""
            if re.search(rf"\b{field_name}\b\s+IN\s*\(", expr):
                enum_values = re.findall(r"'([a-z_0-9]+)'", expr)
                enum_expr = expr
                break

        if enum_values is None:
            errors.append(f"{agg['id']}: {table_name}.{field_name} has no enum constraint")
            continue

        checked += 1
        if set(enum_values) != set(states):
            missing = sorted(set(states) - set(enum_values))
            extra = sorted(set(enum_values) - set(states))
            errors.append(
                f"{agg['id']}: {table_name}.{field_name} enum differs from contract "
                f"(missing={missing}, extra={extra})"
            )

        # the default must be a legal state, otherwise the first insert fails
        field = next((f for f in table["fields"] if f["name"] == field_name), None)
        if field and field.get("default"):
            literal = str(field["default"]).strip().strip("'")
            if literal not in states:
                errors.append(
                    f"{agg['id']}: {table_name}.{field_name} default {literal!r} is not a contract state"
                )

        # Any other constraint that compares the status column to a literal naming
        # a state must use a state that can actually occur. A constraint written
        # against a status the enum forbids is either dead or, worse, unsatisfiable
        # — `(status = 'consumed') = (consumed_at IS NOT NULL)` inverts into
        # "consumed_at is always NULL" once 'consumed' stops being a state.
        for con in table.get("constraints", []):
            expr = con.get("expr") or ""
            if expr is enum_expr:
                continue
            referenced = set(re.findall(rf"\b{field_name}\b\s*=\s*'([a-z_0-9]+)'", expr))
            unreachable = sorted(referenced - set(states))
            if unreachable:
                errors.append(
                    f"{agg['id']}: {table_name}.{field_name} constraint {con['name']} "
                    f"references state(s) the enum forbids: {unreachable}"
                )

    print(f"aggregates with a status enum: {checked}/{len(mapping)}")
    if errors:
        print()
        for e in errors:
            print(f"  - {e}")
        print()
        print("run: python tools/sync_state_enums.py --apply")
        return 1

    print("OK: every status enum matches its frozen state machine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
