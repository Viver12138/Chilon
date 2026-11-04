"""Validator for the Chilon Action Registry.

Checks the relationships that JSON Schema cannot express:

  1. every (aggregate, trigger) in state_machines.v1.json has exactly one action;
  2. every transition id is claimed by exactly one action;
  3. compound groups reference existing actions and are declared exactly once;
  4. teacher actions carry a label, an error list, and only known error codes;
  5. hidden actions carry a description instead of a label;
  6. schema conformance (subset validator, no external dependency).

Usage:
    python design/check_actions.py
    python design/check_actions.py --selftest
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = ROOT / "schemas" / "actions.v1.json"
ACTION_SCHEMA = ROOT / "schemas" / "actions.v1.schema.json"
STATE_MACHINES = ROOT / "schemas" / "state_machines.v1.json"


# --- minimal JSON Schema validator (same subset as check_state_machines.py) ---
def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        node: dict = root
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        schema = node
    return schema


def validate(instance, schema: dict, root: dict, path: str = "$") -> list[str]:
    schema = _resolve(schema, root)
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    if "const" in schema and instance != schema["const"]:
        fail(f"expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        fail(f"{instance!r} not in enum {schema['enum']}")

    stype = schema.get("type")
    if stype == "object":
        if not isinstance(instance, dict):
            fail(f"expected object, got {type(instance).__name__}")
            return errors
        for key in schema.get("required", []):
            if key not in instance:
                fail(f"missing required property {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    fail(f"unexpected property {key!r}")
        for key, sub in props.items():
            if key in instance:
                errors.extend(validate(instance[key], sub, root, f"{path}.{key}"))
    elif stype == "array":
        if not isinstance(instance, list):
            fail(f"expected array, got {type(instance).__name__}")
            return errors
        if len(instance) < schema.get("minItems", 0):
            fail(f"length {len(instance)} < minItems {schema['minItems']}")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root, f"{path}[{i}]"))
    elif stype == "string":
        if not isinstance(instance, str):
            fail(f"expected string, got {type(instance).__name__}")
            return errors
        if len(instance) < schema.get("minLength", 0):
            fail(f"string shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            fail(f"string {instance!r} does not match pattern {schema['pattern']}")
    elif stype == "integer":
        if not isinstance(instance, int) or isinstance(instance, bool):
            fail(f"expected integer, got {type(instance).__name__}")
    return errors


def check_structure(actions: dict, machines: dict) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    known_codes = {c["code"] for c in actions["error_codes"]}
    if len(known_codes) != len(actions["error_codes"]):
        fail("duplicate error code definitions")

    # index state machine transitions
    sm_pairs: dict[tuple[str, str], list[str]] = {}
    sm_transitions: dict[str, set[str]] = {}
    for agg in machines["aggregates"]:
        aid = agg["id"]
        sm_transitions[aid] = {t["id"] for t in agg["transitions"]}
        for tr in agg["transitions"]:
            sm_pairs.setdefault((aid, tr["trigger"]), []).append(tr["id"])

    seen_pairs: set[tuple[str, str]] = set()
    claimed: dict[str, list[str]] = {}
    action_ids: set[str] = set()

    for agg in actions["aggregates"]:
        aid = agg["aggregate"]
        if aid not in sm_transitions:
            fail(f"{aid}: aggregate does not exist in state_machines")
            continue

        for act in agg["actions"]:
            pair = (aid, act["trigger"])
            action_id = f"{aid}.{act['trigger']}"
            if pair in seen_pairs:
                fail(f"{action_id}: duplicate action")
            seen_pairs.add(pair)
            action_ids.add(action_id)

            if pair not in sm_pairs:
                fail(f"{action_id}: no such (aggregate, trigger) in state_machines")

            for tid in act["transitions"]:
                claimed.setdefault(aid, []).append(tid)
                if tid not in sm_transitions[aid]:
                    fail(f"{action_id}: transition {tid} does not exist in {aid}")

            if act["actor"] == "teacher":
                if not act.get("label"):
                    fail(f"{action_id}: teacher action requires a label")
                if not act.get("errors"):
                    fail(f"{action_id}: teacher action requires error codes")
                if act["ui"] == "hidden":
                    fail(f"{action_id}: teacher action must be visible")
            else:
                if act.get("description") is None:
                    fail(f"{action_id}: non-teacher action requires a description")
                if act["ui"] != "hidden":
                    fail(f"{action_id}: non-teacher action must be hidden")

            for code in act.get("errors", []):
                if code not in known_codes:
                    fail(f"{action_id}: unknown error code {code!r}")

    # coverage both ways
    for pair in sm_pairs:
        if pair not in seen_pairs:
            errors.append(f"missing action for {pair[0]}.{pair[1]} (present in state_machines)")
    for aid, tids in sm_transitions.items():
        claimed_set = claimed.get(aid, [])
        dupes = {t for t in claimed_set if claimed_set.count(t) > 1}
        if dupes:
            fail(f"{aid}: transition(s) claimed by more than one action: {sorted(dupes)}")
        missing = tids - set(claimed_set)
        if missing:
            fail(f"{aid}: transition(s) not claimed by any action: {sorted(missing)}")

    # compound groups
    declared = {c["id"]: c for c in actions["compound_commands"]}
    used: dict[str, list[str]] = {}
    for agg in actions["aggregates"]:
        for act in agg["actions"]:
            group = act.get("compound")
            if group is None:
                continue
            action_id = f"{agg['aggregate']}.{act['trigger']}"
            used.setdefault(group, []).append(action_id)
            if group not in declared:
                fail(f"{action_id}: compound {group!r} is not declared in compound_commands")

    for group, cmd in declared.items():
        members = set(cmd["members"])
        actual = set(used.get(group, []))
        if members != actual:
            fail(
                f"compound {group}: declared members {sorted(members)} "
                f"but actions reference {sorted(actual)}"
            )
        if len(cmd["members"]) != len(members):
            fail(f"compound {group}: duplicate members")

    return errors


def check_schema(actions: dict) -> list[str]:
    schema = json.loads(ACTION_SCHEMA.read_text(encoding="utf-8"))
    return validate(actions, schema, schema)


def self_test(actions: dict, machines: dict) -> list[str]:
    failures: list[str] = []

    def expect(desc: str, mutate, checker) -> bool:
        broken = copy.deepcopy(actions)
        mutate(broken)
        if not checker(broken, machines):
            failures.append(f"self-test: {desc} was NOT detected")
            return False
        return True

    def drop_action(a):
        a["aggregates"][0]["actions"] = a["aggregates"][0]["actions"][1:]

    def teacher_without_label(a):
        for agg in a["aggregates"]:
            for act in agg["actions"]:
                if act["actor"] == "teacher":
                    act.pop("label", None)
                    return

    def unknown_error(a):
        for agg in a["aggregates"]:
            for act in agg["actions"]:
                if act.get("errors"):
                    act["errors"] = ["NOT_A_REAL_CODE"]
                    return

    def double_claim(a):
        a["aggregates"][0]["actions"][1]["transitions"].append(
            a["aggregates"][0]["actions"][0]["transitions"][0]
        )

    expect("action removed for an existing (aggregate, trigger)", drop_action, check_structure)
    expect("teacher action without a label", teacher_without_label, check_structure)
    expect("teacher action citing an unknown error code", unknown_error, check_structure)
    expect("transition claimed twice", double_claim, check_structure)
    return failures


def main() -> int:
    actions = json.loads(ACTIONS.read_text(encoding="utf-8"))
    machines = json.loads(STATE_MACHINES.read_text(encoding="utf-8"))

    total = sum(len(a["actions"]) for a in actions["aggregates"])
    teacher = sum(1 for a in actions["aggregates"] for x in a["actions"] if x["actor"] == "teacher")
    hidden = total - teacher

    print(f"actions          : {total}  (teacher {teacher}, system/worker {hidden})")
    print(f"aggregates       : {len(actions['aggregates'])}")
    print(f"compound commands: {len(actions['compound_commands'])}")
    print(f"error codes      : {len(actions['error_codes'])}")

    schema_errors = check_schema(actions)
    structural = check_structure(actions, machines)
    errors = schema_errors + structural

    print()
    print(f"JSON Schema conformance : {'OK' if not schema_errors else f'{len(schema_errors)} error(s)'}")
    print(f"cross-check vs states   : {'OK' if not structural else f'{len(structural)} error(s)'}")
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: every transition is claimed exactly once; compounds and error codes are consistent")

    if "--selftest" in sys.argv:
        result = self_test(actions, machines)
        if result:
            print()
            for f in result:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
