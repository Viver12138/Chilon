"""The TeX parser, checked against the corpus it was written for.

No database and no network: parsing 6050 questions takes a second, so this can run in CI
on every commit. The expectations are taken from the corpus itself, not invented:

* 2012-2026 has 274 papers and 6050 problems;
* a paper's question count must match its `\\begin{problem}` count;
* options must be split out of the stem, not left inside it;
* `\\i` is the imaginary unit, but `\\in` must survive — an earlier version of this parser
  turned every `\\in` into `\\mathrm{i}n`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import tex_parse  # noqa: E402

CONTENT = Path("D:/Chilon/var/_tex_clone/repo/content")

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


SAMPLE = r"""
\FigureLayoutDeclare{img/x.png}{6.5cm}{0bp 0bp 0bp 0bp}
\chapter{2024年新高考I卷}
\section{单选题}
\begin{problem}
已知 \(A=\{x\mid -\sqrt[3]{5}<x<\sqrt[3]{5}\}\)，\(B=\{-3,-1,0,2,3\}\)，则 \(A\cap B=\)（\quad）
\choices
    {\(\{-1,0\}\)}
    {\(\{2,3\}\)}
\end{problem}
\begin{answer}
A
\end{answer}
\begin{solution}
因为 \(1<\sqrt[3]{5}<2\).
\end{solution}
\begin{problem}
若 \(\dfrac{z}{z-1}=1+\i\)，则 \(z=\)（\quad）
\end{problem}
\begin{answer}
C
\end{answer}
"""


def main() -> int:
    print("1. a paper is parsed into problems, options and answers")
    paper = tex_parse.parse_tex(SAMPLE, "fallback")
    check(paper.title == "2024年新高考I卷", f"the chapter becomes the title (got {paper.title})")
    check(len(paper.problems) == 2, f"two problems (got {len(paper.problems)})")
    first, second = paper.problems
    check("A\\cap B" in first.stem, "the stem keeps its LaTeX")
    check("choices" not in first.stem, "the choices command is removed from the stem")
    check(len(first.options) == 2, f"options are split out (got {len(first.options)})")
    check(first.answer == "A", f"the answer is attached (got {first.answer!r})")
    check("sqrt[3]{5}<2" in first.solution, "the solution is attached")
    check(first.section == "单选题", f"the section is carried (got {first.section!r})")

    print("2. \\i becomes the imaginary unit but \\in survives")
    check("\\mathrm{i}" in second.stem, "the dotless i is expanded")
    check("\\mathrm{i}n" not in second.stem, "and it did not eat \\in")
    check(second.options == [], "a problem without choices has no options")
    check(second.answer == "C", f"its answer is C (got {second.answer!r})")

    if not CONTENT.is_dir():
        print(f"\n    skipped corpus totals: {CONTENT} is not present")
    else:
        print("3. the whole 2012-2026 corpus parses without loss")
        files = [
            path
            for year in sorted(CONTENT.iterdir())
            if year.is_dir() and year.name.isdigit() and int(year.name) >= 2012
            for path in sorted(year.glob("*.tex"))
        ]
        total = answered = empty = 0
        bad = 0
        for path in files:
            parsed = tex_parse.parse_file(path)
            if not parsed.problems:
                bad += 1
                continue
            for problem in parsed.problems:
                total += 1
                if problem.answer:
                    answered += 1
                if not problem.stem:
                    empty += 1
        check(len(files) == 274, f"274 papers (got {len(files)})")
        check(bad == 0, f"every paper yields problems (bad={bad})")
        check(total == 6050, f"6050 problems (got {total})")
        check(empty == 0, f"no empty stems (got {empty})")
        check(answered >= 4000, f"at least 4000 answers carried (got {answered})")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: the TeX corpus parses deterministically and keeps its answers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
