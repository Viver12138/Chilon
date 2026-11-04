"""Structural check for a markdown file: fences balanced, tables well formed."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    fence = "`" * 3
    in_code = False
    issues: list[tuple[int, str]] = []
    table_rows: dict[int, int] = {}

    for number, line in enumerate(lines, 1):
        if line.strip().startswith(fence):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("|"):
            if not line.rstrip().endswith("|"):
                issues.append((number, "table row does not end with a pipe"))
            table_rows[number] = line.count("|")

    # every pipe table must have consistent column counts
    block: list[int] = []
    for number in list(table_rows) + [0]:
        if number and (not block or number == block[-1] + 1):
            block.append(number)
            continue
        if block:
            counts = {table_rows[n] for n in block}
            if len(counts) > 1:
                issues.append((block[0], f"table has inconsistent pipe counts {sorted(counts)}"))
            block = [number] if number else []

    print(f"{path.name}: {len(lines)} lines, tables {sum(1 for l in lines if l.startswith('| ---'))}")
    if in_code:
        issues.append((len(lines), "unbalanced code fence"))
    for number, message in issues:
        print(f"  L{number}: {message}")
    if not issues:
        print("  OK: fences balanced, tables consistent")
    return 1 if issues else 0


if __name__ == "__main__":
    target = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "docs/Chilon-用户功能说明.md")
    raise SystemExit(check(target))
