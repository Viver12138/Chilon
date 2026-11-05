"""Textbook chunking: never split mid-sentence, never emit fragments.

No database and no OCR: `split_page` is pure, and it is the part most likely to be
wrong in a way that looks fine (a chunk boundary in the middle of "集合 A 相对于全集 U
的补集" silently loses the sentence's subject).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import textbook_import  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


PAGE = (
    "对于一个集合A，由全集U中不属于集合A的所有元素组成的集合称为集合A相对于全集U的补集"
    "(complementary set)，简称为集合A的补集，记作 \\complement _ { U } A ，"
    "即 A \\complement _ { U } A = \\left\\{ x | x \\in U ， \\right. 且 \\left.{x∉A} } ，"
    "\\complement _ { U } A 可用Venn图(图1.3-4) 表示. "
    "例5 设 U={x|x 是小于9的正整数}， A={1，2，3}，B={3，4，5，6}， 求 \\complement _ { U } A ，"
    "\\complement _ { U } B . 解：根据题意可知， U={1，2，3，4，5，6，7，8} ，"
    "所以 \\complement _ { U } A = \\left\\{ 4 ， 5 ， 6 ， 7 ， 8 \\right\\} ，"
    "\\complement _ { U } B = \\left\\{ 1 ， 2 ， 7 ， 8 \\right\\} . "
    "练习 1.已知 U={1，2，3，4，5，6，7}，A={2，4，5}，B={1，3，5，7}， 求 A \\cap \\left( \\complement _ { U } B \\right) ."
)


def main() -> int:
    print("1. a page becomes passage-sized chunks")
    pieces = textbook_import.split_page(PAGE)
    check(len(pieces) >= 1, f"at least one chunk (got {len(pieces)})")
    check(
        all(len(piece) <= textbook_import.CHUNK_TARGET + 60 for piece in pieces),
        "no chunk exceeds the target by much",
    )
    check(all(len(piece) >= 40 for piece in pieces), "no tiny fragments")

    print("2. the definition stays in one piece")
    joined = "".join(pieces)
    check("补集" in joined, "the definition survives")
    check(
        any("不属于集合A的所有元素" in piece for piece in pieces),
        "and is not cut through the middle of the sentence",
    )

    print("3. the whole page is preserved")
    source_chars = len(PAGE.replace("\n", ""))
    check(
        abs(len(joined) - source_chars) <= 3,
        f"no text lost ({source_chars} -> {len(joined)})",
    )

    print("4. an empty page yields nothing")
    check(textbook_import.split_page("") == [], "empty stays empty")
    check(textbook_import.split_page("   \n\n  ") == [], "whitespace stays empty")

    print("5. the attribution names the actual rights holder")
    check("人民教育出版社" in textbook_import.ATTRIBUTION, "it names 人教社")
    check(
        "Apache-2.0" in textbook_import.ATTRIBUTION,
        "and says the uploader's licence does not cover the content",
    )

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: textbook pages chunk without losing sentences")
    return 0


if __name__ == "__main__":
    sys.exit(main())
