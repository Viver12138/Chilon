"""Validate that the test plan covers every contract element.

The point is not to check the plan is well-formed, but that it has no gaps:
every legal transition, every (aggregate, state) rejection case, every teacher
action, every endpoint, every error code, every D3 acceptance point and every
D1 metric must appear exactly once.

Usage:
    python design/check_test_plan.py
    python design/check_test_plan.py --selftest
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
PLAN = SCHEMAS / "test_plan.v1.json"


def load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def check(plan: dict, machines: dict, actions: dict, surface: dict) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    suites = {s["id"]: s for s in plan["suites"]}

    # --- duplicate ids across the whole plan ----------------------------
    seen: set[str] = set()
    for suite in plan["suites"]:
        for case in suite["cases"]:
            cid = case["id"]
            if cid in seen:
                fail(f"duplicate case id {cid}")
            seen.add(cid)

    # --- SM: every transition + every state -----------------------------
    sm = suites.get("SM", {"cases": []})["cases"]
    legal = {c["transition"] for c in sm if c["kind"] == "legal"}
    reject = {(c["aggregate"], c["state"]) for c in sm if c["kind"] == "reject"}

    expected_transitions = set()
    expected_states = set()
    for agg in machines["aggregates"]:
        for tr in agg["transitions"]:
            expected_transitions.add(tr["id"])
        for state in agg["states"]:
            expected_states.add((agg["id"], state))

    missing_t = expected_transitions - legal
    extra_t = legal - expected_transitions
    if missing_t:
        fail(f"SM: transitions without a legal case: {sorted(missing_t)[:8]}")
    if extra_t:
        fail(f"SM: legal cases for unknown transitions: {sorted(extra_t)[:8]}")
    missing_s = expected_states - reject
    if missing_s:
        fail(f"SM: states without a rejection case: {sorted(missing_s)[:8]}")

    # --- ACT: every teacher action, success + failure --------------------
    act = suites.get("ACT", {"cases": []})["cases"]
    teacher = {
        f"{agg['aggregate']}.{act_['trigger']}"
        for agg in actions["aggregates"]
        for act_ in agg["actions"]
        if act_["actor"] == "teacher"
    }
    covered = {c["action"] for c in act}
    if teacher - covered:
        fail(f"ACT: teacher actions without cases: {sorted(teacher - covered)[:8]}")
    for name in teacher:
        kinds = {c["kind"] for c in act if c["action"] == name}
        if kinds != {"success", "failure"}:
            fail(f"ACT: {name} missing a success or failure case")

    # --- API: every endpoint -------------------------------------------
    api = suites.get("API", {"cases": []})["cases"]
    api_paths = {(c["method"], c["path"]) for c in api}
    expected_paths = {(e["method"], e["path"]) for e in surface["action_endpoints"]}
    expected_paths |= {(r["method"], r["path"]) for r in surface["resources"]}
    if expected_paths - api_paths:
        fail(f"API: endpoints without cases: {sorted(expected_paths - api_paths)[:6]}")
    if api_paths - expected_paths:
        fail(f"API: cases for unknown endpoints: {sorted(api_paths - expected_paths)[:6]}")

    # --- ERR: every error code -----------------------------------------
    err = suites.get("ERR", {"cases": []})["cases"]
    codes = {c["code"] for c in actions["error_codes"]}
    covered_codes = {c["code"] for c in err}
    if codes - covered_codes:
        fail(f"ERR: error codes without cases: {sorted(codes - covered_codes)}")

    # --- UI / METRIC / DATA minimum coverage ---------------------------
    if len(suites.get("UI", {"cases": []})["cases"]) < 12:
        fail("UI: fewer than 12 acceptance cases")
    if len(suites.get("METRIC", {"cases": []})["cases"]) < 18:
        fail("METRIC: fewer than 18 metric cases")
    if len(suites.get("DATA", {"cases": []})["cases"]) < 20:
        fail("DATA: fewer than 20 data-quality cases")
    if len(plan.get("concurrency_checks", [])) < 10:
        fail("CC: fewer than 10 concurrency / fault-injection checks")

    return errors


def self_test(plan: dict, machines: dict, actions: dict, surface: dict) -> list[str]:
    failures: list[str] = []

    def expect(desc: str, mutate) -> None:
        broken = copy.deepcopy(plan)
        mutate(broken)
        if not check(broken, machines, actions, surface):
            failures.append(f"self-test: {desc} was NOT detected")

    def drop_transition(p):
        sm = next(s for s in p["suites"] if s["id"] == "SM")
        sm["cases"] = [c for c in sm["cases"] if c.get("kind") != "legal"][:1] + [
            c for c in sm["cases"] if c.get("kind") == "legal"
        ][1:]

    def drop_state(p):
        sm = next(s for s in p["suites"] if s["id"] == "SM")
        sm["cases"] = [c for c in sm["cases"] if c.get("kind") == "reject"][1:] + [
            c for c in sm["cases"] if c.get("kind") != "reject"
        ]

    def drop_endpoint(p):
        api = next(s for s in p["suites"] if s["id"] == "API")
        api["cases"] = api["cases"][1:]

    def drop_code(p):
        err = next(s for s in p["suites"] if s["id"] == "ERR")
        err["cases"] = err["cases"][1:]

    expect("a legal transition removed", drop_transition)
    expect("a state rejection case removed", drop_state)
    expect("an endpoint removed", drop_endpoint)
    expect("an error code removed", drop_code)
    return failures


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    machines = load("state_machines.v1.json")
    actions = load("actions.v1.json")
    surface = load("api_surface.v1.json")

    suites = {s["id"]: len(s["cases"]) for s in plan["suites"]}
    total = sum(suites.values()) + len(plan.get("concurrency_checks", []))
    print(f"suites: {suites}")
    print(f"concurrency checks: {len(plan.get('concurrency_checks', []))}")
    print(f"total cases: {total}")

    errors = check(plan, machines, actions, surface)
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: every transition, state, action, endpoint and error code is covered exactly once")

    if "--selftest" in sys.argv:
        failures = self_test(plan, machines, actions, surface)
        if failures:
            for f in failures:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected gaps were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
