"""Parse the LaTeX corpus (Gaokao-Math-Problems-Compilation) into a question list.

The corpus gives us what no scan can: exact formulas, and the answers. Each source file
is one paper:

    \\chapter{2024年新高考I卷}
    \\section{单选题}
    \\begin{problem} stem \\choices{o1}{o2}{o3}{o4} \\end{problem}
    \\begin{answer} A \\end{answer}
    \\begin{solution} ... \\end{solution}

The parser is deterministic: no model, no guessing. A question that cannot be parsed is
reported, not invented — 6050 questions is a corpus, and one silently malformed question
is a wrong answer later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CHAPTER = re.compile(r"\\chapter\{([^}]*)\}")
SECTION = re.compile(r"\\section\{([^}]*)\}")
PROBLEM = re.compile(r"\\begin\{problem\}(.*?)\\end\{problem\}", re.S)
ANSWER = re.compile(r"\\begin\{answer\}(.*?)\\end\{answer\}", re.S)
SOLUTION = re.compile(r"\\begin\{solution\}(.*?)\\end\{solution\}", re.S)
CHOICES = re.compile(r"\\choices\s*((?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*)+)", re.S)
CHOICE_ITEM = re.compile(r"\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", re.S)
FIGURE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}")
LAYOUT = re.compile(r"^\\FigureLayoutDeclare\{.*$", re.M)


@dataclass
class Problem:
    ordinal: int
    stem: str
    options: list[str]
    answer: str
    solution: str
    section: str


@dataclass
class ParsedPaper:
    title: str
    problems: list[Problem] = field(default_factory=list)
    unparsed: int = 0


def _clean(value: str) -> str:
    value = LAYOUT.sub("", value)
    value = FIGURE.sub("[图]", value)
    # `\i` is the dotless i used for the imaginary unit; `\in` must survive
    value = re.sub(r"\\i(?![a-zA-Z])", r"\\mathrm{i}", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_tex(text: str, fallback_title: str) -> ParsedPaper:
    title_match = CHAPTER.search(text)
    title = title_match.group(1).strip() if title_match else fallback_title

    paper = ParsedPaper(title=title)
    sections = [(m.start(), m.group(1).strip()) for m in SECTION.finditer(text)]

    matches = list(PROBLEM.finditer(text))
    if not matches:
        paper.unparsed = 1
        return paper

    for index, match in enumerate(matches, start=1):
        body = match.group(1)
        section = ""
        for position, name in sections:
            if position < match.start():
                section = name
            else:
                break

        options: list[str] = []
        choice_match = CHOICES.search(body)
        if choice_match:
            for item in CHOICE_ITEM.findall(choice_match.group(1)):
                cleaned = _clean(item)
                if cleaned:
                    options.append(cleaned)
            body = body[: choice_match.start()] + body[choice_match.end() :]

        tail = text[match.end() : match.end() + 20000]
        answer_match = ANSWER.search(tail)
        solution_match = SOLUTION.search(tail)

        paper.problems.append(
            Problem(
                ordinal=index,
                stem=_clean(body),
                options=options,
                answer=_clean(answer_match.group(1)) if answer_match else "",
                solution=_clean(solution_match.group(1)) if solution_match else "",
                section=section,
            )
        )
    return paper


def parse_file(path: Path) -> ParsedPaper:
    return parse_tex(path.read_text(encoding="utf-8", errors="ignore"), path.stem)
