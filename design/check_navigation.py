"""Validator for the Chilon navigation and gate policy registry.

Checks what JSON alone cannot:

  1. navigation items point at existing pages; page ids and paths are unique;
  2. every page action is a teacher action from actions.v1.json;
  3. every page read path exists in api_surface.v1.json;
  4. every archetype defines all seven gates, using only values the gate allows;
  5. G4–G7 are never auto/not_applicable, and exactly one archetype is default;
  6. golden-path pages each participate in at least one gate;
  7. interaction steps only reference real pages and never exceed the click budget.

Usage:
    python design/check_navigation.py
    python design/check_navigation.py --selftest
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAV = ROOT / "schemas" / "navigation.v1.json"
ACTIONS = ROOT / "schemas" / "actions.v1.json"
SURFACE = ROOT / "schemas" / "api_surface.v1.json"

EVER_REQUIRED = {"G4", "G5", "G6", "G7"}


def check(nav: dict, actions: dict, surface: dict) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    page_ids = [p["id"] for p in nav["pages"]]
    paths = [p["path"] for p in nav["pages"]]
    if len(set(page_ids)) != len(page_ids):
        fail("duplicate page id")
    if len(set(paths)) != len(paths):
        fail("duplicate page path")

    page_by_id = {p["id"]: p for p in nav["pages"]}

    for group in nav["navigation"]:
        for item in group["items"]:
            if item["page"] not in page_by_id:
                fail(f"{item['id']}: navigation points at unknown page {item['page']!r}")

    teacher_actions = {
        f"{agg['aggregate']}.{act['trigger']}"
        for agg in actions["aggregates"]
        for act in agg["actions"]
        if act["actor"] == "teacher"
    }
    surface_paths = {r["path"] for r in surface["resources"]} | {
        e["path"] for e in surface["action_endpoints"]
    }

    for page in nav["pages"]:
        pid = page["id"]
        for action in page["actions"]:
            if action not in teacher_actions:
                fail(f"{pid}: action {action!r} is not a teacher action")
        for read in page["reads"]:
            if read not in surface_paths:
                fail(f"{pid}: read path {read!r} is not in api_surface")
        if page["tier"] == "golden_path" and not page["gates"]:
            fail(f"{pid}: golden-path page must participate in at least one gate")
        if page["tier"] == "deferred" and page["actions"]:
            fail(f"{pid}: deferred page must not reference actions yet")

    policy = nav["gate_policy"]
    gates = policy["gates"]
    allowed = policy["allowed_values"]
    defaults = [a for a in nav["archetypes"] if a.get("default")]
    if len(defaults) != 1:
        fail(f"expected exactly one default archetype, found {len(defaults)}")

    for arch in nav["archetypes"]:
        aid = arch["id"]
        missing = set(gates) - set(arch["policy"])
        if missing:
            fail(f"{aid}: policy missing gates {sorted(missing)}")
        extra = set(arch["policy"]) - set(gates)
        if extra:
            fail(f"{aid}: policy defines unknown gates {sorted(extra)}")
        for gate, value in arch["policy"].items():
            if gate not in allowed:
                continue
            if value not in allowed[gate]:
                fail(f"{aid}: gate {gate} = {value!r} not allowed (allowed {allowed[gate]})")

    for gate in EVER_REQUIRED:
        if "required" not in allowed.get(gate, []):
            fail(f"{gate}: never-optional gate must allow only 'required'")
        if set(allowed.get(gate, [])) != {"required"}:
            fail(f"{gate}: gate must be locked to 'required', found {allowed[gate]}")

    steps = nav["interaction_steps"]
    total = 0
    for row in steps["mapping"]:
        if row["page"] not in page_by_id:
            fail(f"interaction step references unknown page {row['page']!r}")
        total += row["steps"]
        for gate in row["gates"]:
            if gate not in gates:
                fail(f"interaction step references unknown gate {gate!r}")
    if total > steps["max_clicks_full_generation"]:
        fail(f"interaction steps total {total} exceeds budget {steps['max_clicks_full_generation']}")

    return errors


def self_test(nav: dict, actions: dict, surface: dict) -> list[str]:
    failures: list[str] = []

    def expect(desc: str, mutate) -> None:
        broken = copy.deepcopy(nav)
        mutate(broken)
        if not check(broken, actions, surface):
            failures.append(f"self-test: {desc} was NOT detected")

    def drop_gate(a):
        a["archetypes"][0]["policy"].pop("G5")

    def auto_g6(a):
        a["archetypes"][0]["policy"]["G6"] = "auto"

    def bad_action(a):
        next(p for p in a["pages"] if p["actions"])["actions"] = ["draft.teleport"]

    def orphan_nav(a):
        a["navigation"][0]["items"][0]["page"] = "nowhere"

    expect("archetype missing a gate", drop_gate)
    expect("G6 set to auto", auto_g6)
    expect("page citing a nonexistent action", bad_action)
    expect("navigation pointing at a missing page", orphan_nav)
    return failures


def main() -> int:
    nav = json.loads(NAV.read_text(encoding="utf-8"))
    actions = json.loads(ACTIONS.read_text(encoding="utf-8"))
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))

    errors = check(nav, actions, surface)
    tiers = {}
    for p in nav["pages"]:
        tiers[p["tier"]] = tiers.get(p["tier"], 0) + 1
    print(f"pages       : {len(nav['pages'])}  ({', '.join(f'{k} {v}' for k, v in sorted(tiers.items()))})")
    print(f"archetypes  : {len(nav['archetypes'])}  (default: {next(a['id'] for a in nav['archetypes'] if a.get('default'))})")
    print(f"gates       : {len(nav['gate_policy']['gates'])}  locked: {sorted(EVER_REQUIRED)}")
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: navigation, pages, actions and gate policy are consistent")

    if "--selftest" in sys.argv:
        result = self_test(nav, actions, surface)
        if result:
            print()
            for f in result:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
