"""Generate a table of contents and turn prose section references into links.

Anchors follow the GitHub slug algorithm (lowercase, drop punctuation, spaces to
hyphens, `-N` suffix for duplicates), so links work on GitHub, GitLab and most
Markdown previews.

Usage:
    python design/gen_toc.py --check
    python design/gen_toc.py --apply
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "Chilon_Project_Design_Master_Document.md"
TARGETS = [
    MASTER,
    ROOT / "design" / "Chilon_Design_Volume_D1_Product_Closure_Protocol.md",
    ROOT / "design" / "Chilon_Design_Volume_D4_Actions_Errors_And_Copy.md",
    ROOT / "design" / "Chilon_Design_Volume_D5_Api_And_Sse_Contract.md",
    ROOT / "design" / "Chilon_Design_Volume_D2_Information_Architecture.md",
    ROOT / "design" / "Chilon_Design_Volume_D3_Page_Specifications.md",
    ROOT / "design" / "Chilon_Design_Volume_K09_Knowledge_Field_Design.md",
    ROOT / "design" / "Chilon_Design_Volume_D6_Acceptance_And_Test_Matrix.md",
]

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE = re.compile(r"^\s*```")
REF = re.compile(r"详见\s*((?:\d+(?:\.\d+)*)(?:[\s、,和–—-]+\d+(?:\.\d+)*)*)")
NUM = re.compile(r"\d+(?:\.\d+)*")
TOC_START = "[//]: # (toc:start)"
TOC_END = "[//]: # (toc:end)"


def slugify(text: str) -> str:
    text = text.strip().lower()
    kept = []
    for ch in text:
        if ch.isalnum() or ch in "-_ ":
            kept.append(ch)
        elif unicodedata.east_asian_width(ch) in ("W", "F") and ch.isalnum():
            kept.append(ch)
    return "".join(kept).replace(" ", "-")


def build_anchors(lines: list[str]) -> tuple[dict[str, str], list[tuple[int, int, str, str]]]:
    """Return (section-number -> anchor, headings[(level, text, anchor)])."""
    in_fence = False
    seen: dict[str, int] = {}
    by_number: dict[str, str] = {}
    headings: list[tuple[int, int, str, str]] = []
    for idx, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2)
        base = slugify(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchor = base if count == 0 else f"{base}-{count}"
        headings.append((idx, level, text, anchor))
        num = NUM.match(text)
        if num:
            by_number.setdefault(num.group(), anchor)
    return by_number, headings


def render_toc(headings: list[tuple[int, int, str, str]], max_level: int = 2) -> list[str]:
    out = [TOC_START, "## 目录", ""]
    first_part = next(
        (i for i, (_x, lv, t, _a) in enumerate(headings) if lv == 1 and t.startswith("第")),
        len(headings),
    )
    for pos, (_idx, level, text, anchor) in enumerate(headings):
        if pos == 0:
            continue  # document title
        if text.strip() == "目录":
            continue  # the TOC must not list itself
        if level > max_level:
            continue
        # the preface (§0) sits at H2 under the title but belongs at top level
        shown_level = 1 if (pos < first_part and level >= 2) else level
        indent = "  " * (shown_level - 1)
        label = text.replace("|", "\\|")
        out.append(f"{indent}- [{label}](#{anchor})")
    out.extend(["", TOC_END])
    return out


def strip_all_tocs(lines: list[str]) -> list[str]:
    """Remove every existing TOC block, so regeneration is idempotent."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        if "toc:start" in lines[i]:
            j = i
            while j < len(lines) and "toc:end" not in lines[j]:
                j += 1
            i = j + 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def insert_toc(lines: list[str], toc: list[str]) -> list[str]:
    lines = strip_all_tocs(lines)
    first_rule = next(i for i, ln in enumerate(lines) if ln.strip().startswith("---"))
    return lines[:first_rule] + toc + ["", "---"] + lines[first_rule + 1:]


def link_refs(lines: list[str], by_number: dict[str, str]) -> tuple[list[str], int]:
    in_fence = False
    out = []
    converted = 0
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or "详见" not in line:
            out.append(line)
            continue

        def repl(m: re.Match[str]) -> str:
            nonlocal converted
            group = m.group(1)

            def one(nm: re.Match[str]) -> str:
                nonlocal converted
                num = nm.group()
                anchor = by_number.get(num)
                if not anchor:
                    return num
                converted += 1
                return f"[{num}](#{anchor})"

            return "详见 " + NUM.sub(one, group)

        out.append(REF.sub(repl, line))
    return out, converted


def check_links(lines: list[str], anchors: set[str]) -> list[str]:
    bad = []
    for idx, line in enumerate(lines, start=1):
        for m in re.finditer(r"\]\(#([^)]+)\)", line):
            if m.group(1) not in anchors:
                bad.append(f"L{idx}: missing anchor #{m.group(1)}")
    return bad


def main() -> int:
    apply = "--apply" in sys.argv
    for target in TARGETS:
        if not target.exists():
            print(f"SKIP {target.name}")
            continue
        raw = target.read_text(encoding="utf-8")
        lines = raw.splitlines()

        by_number, headings = build_anchors(lines)
        toc = render_toc(headings)
        lines = insert_toc(lines, toc)
        lines, converted = link_refs(lines, by_number)

        by_number2, headings2 = build_anchors(lines)
        anchors = {a for *_x, a in headings2}
        bad = check_links(lines, anchors)

        print(f"{target.name}: headings {len(headings2)} "
              f"(H1 {sum(1 for h in headings2 if h[1] == 1)}, "
              f"H2 {sum(1 for h in headings2 if h[1] == 2)})  "
              f"toc {sum(1 for _i, lv, _t, _a in headings2 if lv <= 2)}  "
              f"refs linked {converted}  broken links {len(bad)}")
        for b in bad[:10]:
            print(f"  {b}")

        if apply:
            target.write_text("\n".join(lines) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    if apply:
        print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
