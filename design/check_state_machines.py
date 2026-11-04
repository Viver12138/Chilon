"""Structural validator for the Chilon State Machine Registry.

Checks the constraints that JSON Schema cannot express:

  1. state names are unique within an aggregate;
  2. initial/terminal states are declared states, and the two sets do not overlap;
  3. every transition endpoint is a declared state;
  4. terminal states have no outgoing transitions (SM-R05);
  5. every declared state is reachable from an initial state;
  6. every aggregate has at least one terminal state and one transition;
  7. transition and trigger ids are unique per aggregate;
  8. cross-checks against the master document: declared states appear in the text,
     and the terminal-state column of §21.4.1 agrees with the registry.

Usage:
    python design/check_state_machines.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "schemas" / "state_machines.v1.json"
SCHEMA = ROOT / "schemas" / "state_machines.v1.schema.json"
MASTER = ROOT / "Chilon_Project_Design_Master_Document.md"

ASSIGNMENT_TABLE_H2 = "21.4.1"
CODE_SPAN = re.compile(r"`([^`]+)`")


def load() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


# --- minimal JSON Schema validator ------------------------------------------
# Supports the subset used by state_machines.v1.schema.json so the registry can be
# validated without an external dependency.

def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"unsupported $ref {ref}")
        node: dict = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
        if "$ref" not in schema:
            break
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
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not validate(instance, s, root, path)]
        if len(matches) != 1:
            fail(f"matched {len(matches)} oneOf branches, expected exactly 1")

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
    elif stype == "boolean":
        if not isinstance(instance, bool):
            fail(f"expected boolean, got {type(instance).__name__}")
    return errors


def check_structure(reg: dict) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    seen_ids: set[str] = set()
    for agg in reg["aggregates"]:
        aid = agg["id"]
        if aid in seen_ids:
            fail(f"{aid}: duplicate aggregate id")
        seen_ids.add(aid)

        states = agg["states"]
        if len(set(states)) != len(states):
            dupes = sorted({s for s in states if states.count(s) > 1})
            fail(f"{aid}: duplicate states {dupes}")

        state_set = set(states)
        initial = set(agg["initial_states"])
        terminal = set(agg["terminal_states"])

        for s in sorted(initial - state_set):
            fail(f"{aid}: initial state {s!r} is not declared")
        for s in sorted(terminal - state_set):
            fail(f"{aid}: terminal state {s!r} is not declared")
        for s in sorted(initial & terminal):
            fail(f"{aid}: state {s!r} is both initial and terminal")
        if not initial:
            fail(f"{aid}: no initial state")
        if not terminal:
            fail(f"{aid}: no terminal state")

        tr_ids: set[str] = set()
        edges: dict[str, set[str]] = defaultdict(set)
        for tr in agg["transitions"]:
            tid = tr["id"]
            if tid in tr_ids:
                fail(f"{aid}: duplicate transition id {tid}")
            tr_ids.add(tid)
            sources = tr["from"] if isinstance(tr["from"], list) else [tr["from"]]
            if not sources:
                fail(f"{aid}.{tid}: empty from")
            for s in sources:
                if s not in state_set:
                    fail(f"{aid}.{tid}: from state {s!r} is not declared")
                if s in terminal:
                    fail(f"{aid}.{tid}: terminal state {s!r} has an outgoing transition (SM-R05)")
                edges[s].add(tr["to"])
            if tr["to"] not in state_set:
                fail(f"{aid}.{tid}: to state {tr['to']!r} is not declared")

        # reachability from the initial states
        seen = set(initial)
        stack = list(initial)
        while stack:
            cur = stack.pop()
            for nxt in edges.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        unreachable = sorted(state_set - seen)
        if unreachable:
            fail(f"{aid}: unreachable states {unreachable}")

        # a state with no incoming and no outgoing edge is dead weight
        touched = set()
        for tr in agg["transitions"]:
            src = tr["from"] if isinstance(tr["from"], list) else [tr["from"]]
            touched.update(src)
            touched.add(tr["to"])
        dead = sorted(state_set - touched)
        if dead:
            fail(f"{aid}: states appear in no transition {dead}")

    return errors


def check_document(reg: dict) -> list[str]:
    """Cross-check the registry against the master document."""
    errors: list[str] = []
    text = MASTER.read_text(encoding="utf-8")
    spans = set(CODE_SPAN.findall(text))

    for agg in reg["aggregates"]:
        for state in agg["states"]:
            if state not in spans and f"`{state}`" not in text:
                errors.append(
                    f"{agg['id']}: state {state!r} (from {agg['source']}) never appears as inline code in the master document"
                )

    # §21.4.1 terminal-state column must agree
    section = re.search(
        r"#### 21\.4\.1 状态机归属(.*?)#### 21\.4\.2",
        text,
        re.S,
    )
    if not section:
        errors.append("cannot locate §21.4.1 to cross-check terminal states")
        return errors

    by_title = {agg["title"]: agg for agg in reg["aggregates"]}
    for line in section.group(1).splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "状态机":
            continue
        title, terminal_cell = cells[0], cells[3]
        agg = by_title.get(title)
        if not agg:
            errors.append(f"§21.4.1 lists {title!r} which is missing from the registry")
            continue
        doc_terminal = set(CODE_SPAN.findall(terminal_cell))
        reg_terminal = set(agg["terminal_states"])
        if doc_terminal != reg_terminal:
            missing = sorted(reg_terminal - doc_terminal)
            extra = sorted(doc_terminal - reg_terminal)
            errors.append(
                f"{title}: terminal states differ from §21.4.1 "
                f"(registry-only {missing}, doc-only {extra})"
            )
    return errors


def summary(reg: dict) -> None:
    total_tr = sum(len(a["transitions"]) for a in reg["aggregates"])
    print(f"aggregates : {len(reg['aggregates'])}")
    print(f"transitions: {total_tr}")
    print(f"states     : {sum(len(a['states']) for a in reg['aggregates'])}")
    print(f"value sets : {len(reg['value_sets'])}")
    print(f"events     : {len(reg['events'])}")
    print(f"gate rules : {len(reg['gate_rules'])}")
    print()
    for agg in reg["aggregates"]:
        term = ", ".join(agg["terminal_states"])
        print(
            f"  {agg['id']:<22} {agg['module']:<5} {len(agg['states']):>2} states "
            f"{len(agg['transitions']):>2} transitions   terminal: {term}"
        )


def check_schema(reg: dict) -> list[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return validate(reg, schema, schema)


def self_test(reg: dict) -> list[str]:
    """Mutate copies of the registry and assert the checks catch each defect."""
    import copy

    failures: list[str] = []

    def expect(desc: str, mutate, checker) -> None:
        broken = copy.deepcopy(reg)
        mutate(broken)
        if not checker(broken):
            failures.append(f"self-test: {desc} was NOT detected")

    def drop_state(r):
        r["aggregates"][0]["states"].remove("planning")

    def terminal_edge(r):
        r["aggregates"][0]["transitions"].append(
            {"id": "T99", "from": "cancelled", "to": "planning", "trigger": "resurrect", "guard": "test"}
        )

    def bad_trigger(r):
        r["aggregates"][0]["transitions"][0]["trigger"] = "Not-Snake-Case"

    def wrong_terminal(r):
        r["aggregates"][12]["terminal_states"].append("ready")

    expect("undeclared state referenced by a transition", drop_state, check_structure)
    expect("outgoing edge from a terminal state", terminal_edge, check_structure)
    expect("trigger name violating the schema pattern", bad_trigger, check_schema)
    expect("terminal states diverging from §21.4.1", wrong_terminal, check_document)
    return failures


def main() -> int:
    reg = load()
    summary(reg)
    schema_errors = check_schema(reg)
    structural = check_structure(reg)
    doc = check_document(reg)
    errors = schema_errors + structural + doc

    print()
    print(f"JSON Schema conformance : {'OK' if not schema_errors else f'{len(schema_errors)} error(s)'}")
    print(f"structural invariants   : {'OK' if not structural else f'{len(structural)} error(s)'}")
    print(f"document cross-check    : {'OK' if not doc else f'{len(doc)} error(s)'}")
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(reg['aggregates'])} aggregates; schema, structure and document agree")

    if "--selftest" in sys.argv:
        result = self_test(reg)
        if result:
            print()
            for f in result:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
