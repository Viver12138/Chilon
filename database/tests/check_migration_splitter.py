"""Validate the migration SQL splitter without needing Alembic installed.

The splitter is the one piece of the migration that can silently corrupt DDL: a
naive split on ';' would cut inside a `$$ ... $$` function body. This test proves
the statements are balanced and complete before Alembic ever runs them.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def classify(stmt: str) -> str:
    """First keyword after stripping leading comment and blank lines."""
    for line in stmt.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        return stripped.split()[0].split("(")[0].upper()
    return "COMMENT"


def main() -> int:
    # stub alembic.op so the revision module imports without the dependency
    stub = types.ModuleType("alembic")
    stub.op = object()
    sys.modules.setdefault("alembic", stub)

    path = ROOT / "backend" / "migrations" / "versions" / "0001_k009_baseline.py"
    if not path.exists():
        print(f"missing {path.relative_to(ROOT)}")
        return 1

    spec = importlib.util.spec_from_file_location("baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    stmts = mod.split_statements(mod.SQL)
    kinds: dict[str, int] = {}
    for stmt in stmts:
        head = classify(stmt)
        kinds[head] = kinds.get(head, 0) + 1

    create_tables = sum(
        1 for s in stmts
        if any(line.strip().upper().startswith("CREATE TABLE") for line in s.splitlines())
    )
    create_functions = sum(
        1 for s in stmts
        if any("CREATE OR REPLACE FUNCTION" in line.upper() for line in s.splitlines())
    )
    unbalanced_dollar = [s for s in stmts if s.count("$$") % 2]
    unbalanced_quote = [s for s in stmts if s.count("'") % 2]

    print(f"statements        : {len(stmts)}")
    print(f"by keyword        : {kinds}")
    print(f"CREATE TABLE      : {create_tables} (expected {len(mod.TABLES)})")
    print(f"CREATE FUNCTION   : {create_functions} (expected 3)")
    print(f"unbalanced $$     : {len(unbalanced_dollar)}")
    print(f"unbalanced quote  : {len(unbalanced_quote)}")

    failures = []
    if create_tables != len(mod.TABLES):
        failures.append("CREATE TABLE count mismatch")
    if create_functions != 3:
        failures.append("function count mismatch")
    if unbalanced_dollar or unbalanced_quote:
        failures.append("unbalanced quoting")
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("OK: statements are balanced and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
