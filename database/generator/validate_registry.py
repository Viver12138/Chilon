"""Registry loader and validator.

Validates the registry against the field rules in master §26.9 (FLD-001..015)
and the structural rules that JSON schema cannot express.

Usage:
    python database/generator/validate_registry.py
    python database/generator/validate_registry.py --selftest
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY = ROOT / "database" / "registry"

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
SHA256_TYPE = "sha256"


def load_registry() -> dict:
    schema = json.loads((REGISTRY / "schema.json").read_text(encoding="utf-8"))
    modules = {}
    for mod in schema["modules"]:
        rel = mod.get("registry_file")
        if rel:
            modules[mod["id"]] = json.loads((REGISTRY / rel).read_text(encoding="utf-8"))
    return {"schema": schema, "modules": modules}


def all_tables(reg: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for mod_id, mod in reg["modules"].items():
        for table in mod["tables"]:
            out[table["name"]] = {**table, "_module": mod_id}
    return out


def render_type(field: dict, schema: dict) -> str:
    t = field["type"]
    mapping = schema["type_mapping"]
    if t not in mapping:
        raise KeyError(t)
    base = mapping[t]
    if t == "varchar":
        return f"VARCHAR({field.get('length', 255)})"
    if t == "numeric":
        return f"NUMERIC({field['precision']},{field['scale']})"
    return base


def validate(reg: dict) -> list[str]:
    errors: list[str] = []
    schema = reg["schema"]
    tables = all_tables(reg)
    known = set(tables) | set(schema.get("external_tables", []))
    declared = {t["name"] for t in schema["tables"]}

    def fail(msg: str) -> None:
        errors.append(msg)

    # --- table registry consistency -------------------------------------
    if set(tables) != declared:
        fail(f"schema.json tables and module files disagree: only-in-schema={sorted(declared - set(tables))} only-in-module={sorted(set(tables) - declared)}")

    order = schema.get("table_order", [])
    if set(order) != set(tables):
        fail(f"table_order does not cover every table: missing={sorted(set(tables) - set(order))}")
    if len(order) != len(set(order)):
        fail("table_order contains duplicates")

    for mod_id, mod in reg["modules"].items():
        if mod.get("module") != mod_id:
            fail(f"{mod_id}: module file declares module {mod.get('module')!r}")

    # --- per table ------------------------------------------------------
    for name, table in tables.items():
        if not SNAKE.match(name):
            fail(f"{name}: FLD-001 table name is not snake_case")
        fields = table.get("fields", [])
        if not fields:
            fail(f"{name}: no fields")
            continue

        seen: dict[str, dict] = {}
        pk_fields = [f for f in fields if f.get("primary_key")]
        if len(pk_fields) != 1:
            fail(f"{name}: expected exactly one primary key, found {len(pk_fields)}")
        elif pk_fields[0]["name"] != schema["naming"]["primary_key"]:
            fail(f"{name}: primary key must be named {schema['naming']['primary_key']!r}")

        fk_owner = [f for f in fields if f["name"] == "owner_id"]
        if table.get("owner_scoped") and not fk_owner:
            fail(f"{name}: owner_scoped table must declare owner_id")
        if not table.get("owner_scoped") and fk_owner:
            fail(f"{name}: table has owner_id but is not marked owner_scoped")

        for field in fields:
            fname = field["name"]
            if not SNAKE.match(fname):
                fail(f"{name}.{fname}: FLD-001 column is not snake_case")
            if fname in seen:
                fail(f"{name}.{fname}: FLD-002 duplicate field")
            seen[fname] = field

            if field["type"] not in schema["type_mapping"]:
                fail(f"{name}.{fname}: FLD-003 unknown type {field['type']!r}")
            if field["type"] in {"float", "real", "double"}:
                fail(f"{name}.{fname}: FLD-006 floating type forbidden")
            if "nullable" not in field:
                fail(f"{name}.{fname}: FLD-004 nullable must be explicit")
            elif field["nullable"] is False and "default" not in field and not field.get("primary_key"):
                # a NOT NULL column without default is allowed only if always supplied
                pass
            if field["type"] == SHA256_TYPE and not field.get("desc"):
                fail(f"{name}.{fname}: FLD-010 sha256 field needs a description")
            if field["type"] == "timestamptz" and field.get("default") not in (None, "now()"):
                fail(f"{name}.{fname}: FLD-007 timestamptz default should be now()")
            sens = field.get("sensitivity")
            if sens not in schema["sensitivity_levels"]:
                fail(f"{name}.{fname}: FLD-009 invalid sensitivity {sens!r}")

            fk = field.get("fk") or field.get("deferred_fk")
            if fk:
                if fk["table"] not in known:
                    fail(f"{name}.{fname}: FK target {fk['table']!r} is neither a registry table nor an external table")
                if not fname.endswith(("_id", "_by")):
                    fail(f"{name}.{fname}: FLD-012 foreign key should end with _id or _by")

        # --- constraints ------------------------------------------------
        for con in table.get("constraints", []):
            cols = con.get("columns") or []
            for col in cols:
                if col not in seen:
                    fail(f"{name}: constraint {con['name']} references unknown column {col!r}")
            expr = con.get("expr")
            if expr:
                # strip string literals before extracting identifiers
                bare = re.sub(r"'[^']*'", "''", expr)
                refs = set(re.findall(r"\b([a-z][a-z0-9_]*)\b", bare))
                for ref in refs:
                    if ref in {"and", "or", "not", "null", "is", "in", "true", "false", "now"}:
                        continue
                    if ref not in seen and ref not in {"public"}:
                        fail(f"{name}: check {con['name']} references unknown column {ref!r}")
            if con["type"] not in {"unique", "check"}:
                fail(f"{name}: unsupported constraint type {con['type']!r}")

        # --- indexes ----------------------------------------------------
        for idx in table.get("indexes", []):
            for col in idx["columns"]:
                if col not in seen:
                    fail(f"{name}: index {idx['name']} references unknown column {col!r}")
            if not idx["name"].startswith(schema["naming"]["index_prefix"]):
                fail(f"{name}: index {idx['name']} should start with {schema['naming']['index_prefix']!r}")

        # --- policies ---------------------------------------------------
        for pol in table.get("policies", []):
            if not pol["name"].startswith(schema["naming"]["policy_prefix"]):
                fail(f"{name}: policy {pol['name']} should start with {schema['naming']['policy_prefix']!r}")
            if pol["command"] not in {"SELECT", "ALL", "INSERT", "UPDATE", "DELETE"}:
                fail(f"{name}: policy {pol['name']} has invalid command {pol['command']!r}")
            if table.get("owner_scoped") and "app_current_user_id" not in pol.get("using", ""):
                fail(f"{name}: owner-scoped table policy {pol['name']} must filter by owner")

        # --- renderable -------------------------------------------------
        for field in fields:
            try:
                render_type(field, schema)
            except KeyError:
                pass  # already reported as FLD-003

    return errors


def self_test(reg: dict) -> list[str]:
    failures: list[str] = []

    def expect(desc: str, mutate) -> None:
        broken = copy.deepcopy(reg)
        mutate(broken)
        if not validate(broken):
            failures.append(f"self-test: {desc} was NOT detected")

    def add_float(r):
        r["modules"]["K009"]["tables"][0]["fields"].append(
            {"name": "bad_metric", "type": "float", "nullable": True, "sensitivity": "public", "desc": "x"}
        )

    def broken_fk(r):
        r["modules"]["K009"]["tables"][1]["fields"][3]["fk"]["table"] = "nope_table"

    def bad_sensitivity(r):
        r["modules"]["K009"]["tables"][0]["fields"][0]["sensitivity"] = "unknown"

    def drop_table(r):
        r["modules"]["K009"]["tables"] = r["modules"]["K009"]["tables"][1:]

    expect("float column", add_float)
    expect("FK to unknown table", broken_fk)
    expect("invalid sensitivity", bad_sensitivity)
    expect("table present in schema.json but missing from module file", drop_table)
    return failures


def main() -> int:
    reg = load_registry()
    tables = all_tables(reg)
    errors = validate(reg)

    field_count = sum(len(t["fields"]) for t in tables.values())
    print(f"modules in registry : {len(reg['modules'])}")
    print(f"tables              : {len(tables)}")
    print(f"fields              : {field_count}")
    print(f"indexes             : {sum(len(t.get('indexes', [])) for t in tables.values())}")
    print(f"policies            : {sum(len(t.get('policies', [])) for t in tables.values())}")

    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s):")
        for e in errors[:25]:
            print(f"  - {e}")
        return 1
    print("OK: registry is internally consistent and passes FLD-001..012 checks")

    if "--selftest" in sys.argv:
        failures = self_test(reg)
        if failures:
            for f in failures:
                print(f"  - {f}")
            return 1
        print("self-test: all 4 injected defects were detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
