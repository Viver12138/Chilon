"""Deterministic DDL generator.

Same registry + same generator version must produce byte-identical SQL and the
same hash. `--check` regenerates in memory and compares with the committed file,
so CI fails when the registry changed but the generated SQL was not refreshed.

Usage:
    python database/generator/generate_ddl.py            # write files
    python database/generator/generate_ddl.py --check    # drift check only
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY = ROOT / "database" / "registry"
OUT_DIR = ROOT / "database" / "generated"
GENERATOR_VERSION = "0.1.0"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_registry import all_tables, load_registry, render_type  # noqa: E402


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def registry_hash(reg: dict) -> str:
    payload = canonical(reg["schema"]) + "".join(
        canonical(reg["modules"][mid]) for mid in sorted(reg["modules"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def column_sql(table: str, field: dict, schema: dict) -> str:
    parts = [f'    "{field["name"]}"', render_type(field, schema)]
    if not field.get("nullable", True):
        parts.append("NOT NULL")
    if "default" in field:
        parts.append(f"DEFAULT {field['default']}")
    return " ".join(parts)


def render_table(table: dict, schema: dict, known: set[str], external: set[str]) -> list[str]:
    name = table["name"]
    lines = [f"-- {table.get('purpose', '')}", f"CREATE TABLE {name} ("]
    cols = [column_sql(name, f, schema) for f in table["fields"]]
    pk = next(f["name"] for f in table["fields"] if f.get("primary_key"))
    cols.append(f'    CONSTRAINT pk_{name} PRIMARY KEY ("{pk}")')

    for field in table["fields"]:
        fk = field.get("fk")
        if fk and fk["table"] in known:
            cols.append(
                f'    CONSTRAINT fk_{name}_{field["name"]} FOREIGN KEY ("{field["name"]}") '
                f'REFERENCES {fk["table"]}(id) ON DELETE {fk.get("on_delete", "RESTRICT")}'
            )

    for con in table.get("constraints", []):
        if con["type"] == "unique":
            cols_cols = ", ".join(f'"{c}"' for c in con["columns"])
            cols.append(f'    CONSTRAINT {con["name"]} UNIQUE ({cols_cols})')
        elif con["type"] == "check":
            cols.append(f'    CONSTRAINT {con["name"]} CHECK ({con["expr"]})')

    lines.extend(", ".join([]) or [c + ("," if i < len(cols) - 1 else "") for i, c in enumerate(cols)])
    lines.append(");")
    lines.append("")

    for field in table["fields"]:
        fk = field.get("fk")
        if fk and fk["table"] in external:
            lines.append(
                f'-- DEFERRED FK: {name}."{field["name"]}" -> {fk["table"]}(id) '
                f'(target owned by another module; add after that module is created)'
            )
    if any(f.get("fk", {}).get("table") in external for f in table["fields"]):
        lines.append("")

    lines.append(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;")
    lines.append(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY;")
    for pol in table.get("policies", []):
        using = f' USING ({pol["using"]})' if pol.get("using") else ""
        check = f' WITH CHECK ({pol["with_check"]})' if pol.get("with_check") else ""
        lines.append(f'CREATE POLICY {pol["name"]} ON {name} FOR {pol["command"]}{using}{check};')
    lines.append("")

    for idx in table.get("indexes", []):
        unique = "UNIQUE " if idx.get("unique") else ""
        cols = ", ".join(f'"{c}"' for c in idx["columns"])
        where = f' WHERE {idx["where"]}' if idx.get("where") else ""
        lines.append(f'CREATE {unique}INDEX {idx["name"]} ON {name} ({cols}){where};')
    if table.get("indexes"):
        lines.append("")

    return lines


def generate(reg: dict) -> tuple[str, dict]:
    schema = reg["schema"]
    tables = all_tables(reg)
    known = set(tables)
    external = set(schema.get("external_tables", []))

    order: list[str] = []
    for mod in reg["modules"].values():
        order = order or mod.get("table_order", [])
    order = order or sorted(tables)

    optional = {t["name"] for t in tables.values() if t.get("optional")}

    header = [
        "-- GENERATED FILE — do not edit by hand.",
        f"-- generator: database/generator/generate_ddl.py v{GENERATOR_VERSION}",
        f"-- registry_version: {schema['registry_version']}",
        f"-- registry_hash: {registry_hash(reg)}",
        "-- regenerate with: python database/generator/generate_ddl.py",
        "",
    ]

    body: list[str] = []
    if any(t.get("requires_extension") for t in tables.values()):
        body.append("-- Optional extension required by some tables:")
        for ext in schema.get("extensions", []):
            state = "required" if ext.get("required") else "optional"
            body.append(f"-- CREATE EXTENSION IF NOT EXISTS {ext['name']};  -- {state}: {ext.get('notes','')}")
        body.append("")

    for name in order:
        table = tables[name]
        if table.get("optional"):
            body.append(f"-- OPTIONAL TABLE (requires {table.get('requires_extension','an extension')}): skip if absent")
        body.extend(render_table(table, schema, known, external))

    body.append("-- Grants are intentionally not generated: they depend on deployment roles.")
    body.append(f"-- Runtime role must not own tables or have BYPASSRLS (see §10.2).")

    sql = "\n".join(header + body).rstrip() + "\n"

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "registry_version": schema["registry_version"],
        "registry_hash": registry_hash(reg),
        "schema_hash": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "tables": len(tables),
        "fields": sum(len(t["fields"]) for t in tables.values()),
        "indexes": sum(len(t.get("indexes", [])) for t in tables.values()),
        "policies": sum(len(t.get("policies", [])) for t in tables.values()),
        "optional_tables": sorted(optional),
        "external_tables": sorted(external),
        "output": "database/generated/k009.sql",
    }
    return sql, manifest


def main() -> int:
    reg = load_registry()
    sql, manifest = generate(reg)

    sql_path = OUT_DIR / "k009.sql"
    manifest_path = OUT_DIR / "manifest.json"

    if "--check" in sys.argv:
        if not sql_path.exists():
            print(f"DRIFT: {sql_path.relative_to(ROOT)} does not exist")
            return 1
        current = sql_path.read_text(encoding="utf-8")
        if current != sql:
            print("DRIFT: generated SQL differs from the committed file; rerun the generator")
            return 1
        print(f"OK: generated SQL matches registry (schema_hash {manifest['schema_hash'][:12]})")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(sql, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {sql_path.relative_to(ROOT)} ({len(sql.splitlines())} lines)")
    print(f"wrote {manifest_path.relative_to(ROOT)}")
    print(f"registry_hash {manifest['registry_hash'][:12]}  schema_hash {manifest['schema_hash'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
