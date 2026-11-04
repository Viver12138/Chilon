"""Lightweight markdown sanity checks for the Chilon design docs.

Checks that pipe tables are well formed (consistent column count inside each
table) and that fenced code blocks are balanced. Catches rendering breakage
that plain editing tends to introduce.

Usage:
    python design/check_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / "Chilon_Project_Design_Master_Document.md",
    ROOT / "design" / "Chilon_Design_Volume_D1_Product_Closure_Protocol.md",
    ROOT / "design" / "Chilon_Design_Volume_D4_Actions_Errors_And_Copy.md",
    ROOT / "design" / "Chilon_Design_Volume_D5_Api_And_Sse_Contract.md",
    ROOT / "design" / "Chilon_Design_Volume_D2_Information_Architecture.md",
    ROOT / "design" / "Chilon_Design_Volume_D3_Page_Specifications.md",
    ROOT / "design" / "Chilon_Design_Volume_K09_Knowledge_Field_Design.md",
    ROOT / "design" / "Chilon_Design_Volume_D6_Acceptance_And_Test_Matrix.md",
    ROOT / "design" / "walkthrough" / "Walkthrough_Kit.md",
    ROOT / "design" / "OPEN_ITEMS.md",
]

FENCE = re.compile(r"^\s*(```|~~~)")


def strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()

    fences = sum(1 for ln in lines if FENCE.match(ln))
    if fences % 2:
        problems.append(f"unbalanced code fences ({fences} markers)")

    header_pipes = 0
    in_table = False
    for idx, line in enumerate(lines, start=1):
        if FENCE.match(line):
            in_table = False
            header_pipes = 0
            continue
        stripped = strip_inline_code(line).rstrip()
        is_table_row = stripped.startswith("|")
        if is_table_row:
            pipes = stripped.count("|")
            if not in_table:
                in_table = True
                header_pipes = pipes
            elif pipes != header_pipes:
                problems.append(
                    f"line {idx}: table column mismatch "
                    f"({pipes} pipes, header has {header_pipes}): {line.strip()[:80]}"
                )
        else:
            in_table = False
            header_pipes = 0
    return problems


def main() -> int:
    total = 0
    for path in TARGETS:
        if not path.exists():
            print(f"SKIP {path} (missing)")
            continue
        problems = check_file(path)
        total += len(problems)
        status = "OK " if not problems else "ERR"
        print(f"{status} {path.relative_to(ROOT)}")
        for p in problems:
            print(f"      - {p}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
