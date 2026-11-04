"""Text normalization for the Chilon design documents.

  * `--` -> en dash `–` and `---` -> em dash `—` (pandoc leftovers that render
    as literal hyphens)
  * straight double quotes -> Chinese curly quotes “ ”
  * join pandoc-style mid-sentence line wraps (a soft break renders as a space,
    which shows up as a stray gap inside CJK sentences)
  * trailing whitespace removal

Transformations skip fenced code blocks, inline code spans, link targets,
table separators and horizontal rules.

Usage:
    python design/normalize_text.py --check
    python design/normalize_text.py --apply
"""

from __future__ import annotations

import re
import sys
import unicodedata
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

# only a genuine double hyphen, never part of a 3+ run (tables, rules, front matter)
DOUBLE_HYPHEN = re.compile(r"(?<!-)--(?!-)")
TRIPLE_HYPHEN = re.compile(r"(?<!-)---(?!-)")
TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
RULE = re.compile(r"^\s*-{3,}\s*$")
PROTECTED = re.compile(r"(`[^`]*`|\]\([^)]*\))")

TERMINAL = "。！？；：」』）).!?:;|"
CJK_START = re.compile(r"^[\u4e00-\u9fff]")
# a continuation line never starts a new list item
LIST_START = re.compile(r"^(\d{1,3}[.)]|[-*+]|\(?\d{1,3}\))\s")


def split_protected(line: str) -> list[tuple[bool, str]]:
    """Return [(is_protected, text), ...]; code spans and link targets are frozen."""
    parts = PROTECTED.split(line)
    return [(i % 2 == 1, part) for i, part in enumerate(parts) if part != ""]


def transform_line(line: str, toggle: list[bool]) -> tuple[str, int]:
    result = []
    odd = 0
    for is_code, text in split_protected(line):
        if is_code:
            result.append(text)
            continue
        text = TRIPLE_HYPHEN.sub("—", text)
        text = DOUBLE_HYPHEN.sub("–", text)
        chars = []
        for ch in text:
            if ch == '"':
                chars.append("”" if toggle[0] else "“")
                toggle[0] = not toggle[0]
            else:
                chars.append(ch)
        result.append("".join(chars))
    if toggle[0]:
        odd = 1
        toggle[0] = False
    return "".join(result), odd


def is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F") and "\u4e00" <= ch <= "\u9fff"


def can_join(prev: str, nxt: str) -> bool:
    p, n = prev.strip(), nxt.strip()
    if not p or not n:
        return False
    if prev.endswith("\\"):  # Markdown hard break
        return False
    if p.startswith(("|", "#", ">")):
        return False
    if n.startswith(("|", "#", ">", "```", "---")) or LIST_START.match(n):
        return False
    if RULE.match(prev) or TABLE_SEP.match(prev):
        return False
    if p.endswith(tuple(TERMINAL)):
        return False
    # continue with any word character (CJK is alphanumeric) or an inline code span
    return bool(n[0].isalnum() or n[0] == "`")


def join_wrapped(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    joined = 0
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and out and can_join(out[-1], line):
            nxt = line.strip()
            # the documents space Latin/CJK boundaries, so only CJK-CJK joins
            # are glued without a space
            glue = "" if (is_cjk(out[-1][-1]) and is_cjk(nxt[0])) else " "
            out[-1] = out[-1] + glue + nxt
            joined += 1
            continue
        out.append(line)
    return out, joined


def process(path: Path, apply: bool) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    punctuation = 0
    odd_lines: list[int] = []
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line.rstrip())
            continue
        if in_fence or TABLE_SEP.match(line) or RULE.match(line):
            out.append(line.rstrip())
            continue
        new, odd = transform_line(line, [False])
        if odd:
            odd_lines.append(idx)
        if new.rstrip() != line.rstrip():
            punctuation += 1
        out.append(new.rstrip())

    out, joined = join_wrapped(out)
    if apply:
        path.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    return {
        "punctuation": punctuation,
        "joined": joined,
        "lines_before": len(lines),
        "lines_after": len(out),
        "odd_quotes": len(odd_lines),
    }


def main() -> int:
    apply = "--apply" in sys.argv
    for path in TARGETS:
        if not path.exists():
            continue
        stats = process(path, apply)
        verb = "applied" if apply else "pending"
        print(
            f"{path.name}: {verb} punctuation={stats['punctuation']} "
            f"joins={stats['joined']} lines {stats['lines_before']}->{stats['lines_after']}"
        )
        if stats["odd_quotes"]:
            print(f"  unbalanced quotes on {stats['odd_quotes']} line(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
