"""Validator for the Chilon API surface.

Checks relationships that a schema cannot express:

  1. every teacher action in actions.v1.json has exactly one action endpoint;
  2. every action endpoint references an existing teacher action;
  3. no duplicate method+path, and action paths carry the aggregate's path param;
  4. endpoint error codes are a subset of the registry's known codes;
  5. resource paths do not collide with action paths;
  6. every resource endpoint declares its concurrency/pagination model.

Usage:
    python design/check_api_surface.py
    python design/check_api_surface.py --selftest
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE = ROOT / "schemas" / "api_surface.v1.json"
ACTIONS = ROOT / "schemas" / "actions.v1.json"

PARAM_OF = {
    "task": "task_id",
    "requirement_version": "requirement_version_id",
    "plan_version": "plan_version_id",
    "plan_approval": "plan_approval_id",
    "execution": "execution_id",
    "draft": "draft_id",
    "export": "export_id",
}

VALID_CONCURRENCY = {
    "none",
    "cursor",
    "etag",
    "immutable",
    "idempotency",
}


def check(surface: dict, actions: dict) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(msg)

    teacher_actions = {
        f"{agg['aggregate']}.{act['trigger']}"
        for agg in actions["aggregates"]
        for act in agg["actions"]
        if act["actor"] == "teacher"
    }
    known_codes = {c["code"] for c in actions["error_codes"]}

    seen_names: set[str] = set()
    seen_paths: set[tuple[str, str]] = set()

    for ep in surface["action_endpoints"]:
        name = ep["name"]
        if name not in teacher_actions:
            fail(f"{name}: endpoint references an action that is not a teacher action")
        if name in seen_names:
            fail(f"{name}: duplicate endpoint for the same action")
        seen_names.add(name)

        key = (ep["method"], ep["path"])
        if key in seen_paths:
            fail(f"{ep['method']} {ep['path']}: duplicate method+path")
        seen_paths.add(key)

        if ep["method"] != "POST":
            fail(f"{name}: action endpoints must be POST")

        param = PARAM_OF.get(ep["aggregate"])
        if param and f"{{{param}}}" not in ep["path"]:
            fail(f"{name}: path {ep['path']} missing path parameter {{{param}}}")

        if not ep["path"].endswith(f"/actions/{ep['trigger'].replace('_', '-')}"):
            fail(f"{name}: path must end with /actions/{ep['trigger'].replace('_', '-')}")

        for code in ep["errors"]:
            if code not in known_codes:
                fail(f"{name}: unknown error code {code!r}")

    missing = teacher_actions - seen_names
    for name in sorted(missing):
        fail(f"missing endpoint for teacher action {name}")

    for res in surface["resources"]:
        key = (res["method"], res["path"])
        if key in seen_paths:
            fail(f"resource {res['method']} {res['path']} collides with an action endpoint")
        seen_paths.add(key)
        if res["concurrency"] not in VALID_CONCURRENCY:
            fail(f"resource {res['method']} {res['path']}: invalid concurrency {res['concurrency']!r}")

    sse = surface["sse"]
    if not sse["path"].startswith("/conversations/"):
        fail("SSE path must live under /conversations/")
    if "Last-Event-ID" not in sse["replay"]:
        fail("SSE replay must document Last-Event-ID")

    return errors


def self_test(surface: dict, actions: dict) -> list[str]:
    failures: list[str] = []

    def expect(desc: str, mutate) -> None:
        broken = copy.deepcopy(surface)
        mutate(broken)
        if not check(broken, actions):
            failures.append(f"self-test: {desc} was NOT detected")

    def drop_ep(s):
        s["action_endpoints"] = s["action_endpoints"][1:]

    def dup_path(s):
        s["action_endpoints"][1]["path"] = s["action_endpoints"][0]["path"]

    def bad_code(s):
        s["action_endpoints"][0]["errors"] = ["MADE_UP_CODE"]

    def collide(s):
        s["resources"][0]["method"] = "POST"
        s["resources"][0]["path"] = s["action_endpoints"][0]["path"]

    expect("action endpoint removed", drop_ep)
    expect("duplicate method+path", dup_path)
    expect("endpoint citing an unknown error code", bad_code)
    expect("resource colliding with an action path", collide)
    return failures


def main() -> int:
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))
    actions = json.loads(ACTIONS.read_text(encoding="utf-8"))

    errors = check(surface, actions)
    total = len(surface["action_endpoints"]) + len(surface["resources"])
    print(f"base path        : {surface['base_path']}")
    print(f"action endpoints : {len(surface['action_endpoints'])}")
    print(f"resource endpoints: {len(surface['resources'])}")
    print(f"total endpoints  : {total}")
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK: every teacher action has exactly one endpoint; paths and error codes are consistent")

    if "--selftest" in sys.argv:
        result = self_test(surface, actions)
        if result:
            print()
            for f in result:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
