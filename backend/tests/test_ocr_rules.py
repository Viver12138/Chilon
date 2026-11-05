"""Pure OCR rules, checked without a database or a vendor call.

Both cases here are bugs that were found the hard way, and both are invisible in counts:

* a paper numbered `（1）（2）` was merged into **one** question, because `(n)` was treated
  as a sub-question unconditionally;
* the fix for that raised `list index out of range` on the first question of every paper,
  because `merged[-1]` was read before checking the list was empty.

Neither would have been caught by "the import printed a number".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import ocr  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


class Q:
    """Minimal stand-in for a vendor question."""

    def __init__(self, stem: str, number: str | None = None) -> None:
        self.stem = stem
        self.number = number
        self.page = 1
        self.box = None
        self.analysis = ""
        self.answer = ""


def main() -> int:
    print("1. a parenthesised number is recognised, but only on request")
    check(ocr.paren_number("（1）若集合 A") == 1, "（1） reads as 1")
    check(ocr.paren_number("(2)设 x") == 2, "(2) reads as 2")
    check(ocr.leading_number("（1）若集合 A") is None, "leading_number leaves it alone")

    print("2. a paper numbered （1）（2） keeps its questions apart")
    paren_paper = [Q("（1）第一题"), Q("（2）第二题"), Q("（3）第三题"), Q("（4）第四题")]
    merged = ocr.merge_fragments(paren_paper)
    check(len(merged) == 4, f"four questions, not one (got {len(merged)})")

    print("3. a paper numbered 1. still treats （2） as a sub-question")
    numbered_paper = [
        Q("1.已知集合"),
        Q("（1）第一小问"),
        Q("（2）第二小问"),
        Q("2.已知向量"),
    ]
    merged = ocr.merge_fragments(numbered_paper)
    check(len(merged) == 2, f"two questions (got {len(merged)})")
    check("（1）第一小问" in merged[0].stem, "the sub-question stayed inside question 1")

    print("4. an empty input does not crash")
    check(ocr.merge_fragments([]) == [], "empty list in, empty list out")
    check(ocr.merge_fragments([Q("（1）唯一一题")]) != [], "a single question survives")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: numbering styles behave as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
