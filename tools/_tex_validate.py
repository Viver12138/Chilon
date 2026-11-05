"""Validate the TeX parser against the whole corpus before importing anything."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app.services import tex_parse  # noqa: E402

CONTENT = ROOT / "var/_tex_clone/repo/content"


def main() -> int:
    since = int(sys.argv[1]) if len(sys.argv) > 1 else 2012
    files = [
        path
        for year in sorted(CONTENT.iterdir())
        if year.is_dir() and year.name.isdigit() and int(year.name) >= since
        for path in sorted(year.glob("*.tex"))
    ]
    total = with_answer = with_options = unparsed = 0
    empty_stems = 0
    bad_titles = 0
    samples: list[str] = []
    for path in files:
        paper = tex_parse.parse_file(path)
        if not paper.problems:
            unparsed += 1
            continue
        if paper.title == path.stem:
            bad_titles += 1
        for problem in paper.problems:
            total += 1
            if problem.answer:
                with_answer += 1
            if problem.options:
                with_options += 1
            if not problem.stem:
                empty_stems += 1
        if len(samples) < 3 and paper.problems:
            first = paper.problems[0]
            samples.append(
                f"{paper.title} | q1 stem={first.stem[:60]!r} options={len(first.options)} "
                f"answer={first.answer[:10]!r}"
            )

    print(f"files                : {len(files)}")
    print(f"problems             : {total}")
    print(f"with answer          : {with_answer} ({with_answer / max(total, 1):.0%})")
    print(f"with options         : {with_options}")
    print(f"empty stems          : {empty_stems}")
    print(f"files without problems: {unparsed}")
    print(f"title fell back to filename: {bad_titles}")
    print("\nsamples:")
    for line in samples:
        print("  -", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
