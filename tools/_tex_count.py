"""Count problems and answers available in the TeX corpus (2012-2026)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("D:/Chilon/var/_tex_clone/repo/content")
PROBLEM = re.compile(r"\\begin\{problem\}")
CHOICES = re.compile(r"\\choices")
ANSWER = re.compile(r"\\begin\{answer\}")
SOLUTION = re.compile(r"\\begin\{solution\}")
CHAPTER = re.compile(r"\\chapter\{([^}]*)\}")


def main() -> int:
    years = sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.isdigit())
    total = 0
    in_range = 0
    in_range_files = 0
    rows = []
    for year_dir in years:
        problems = answers = 0
        files = sorted(year_dir.glob("*.tex"))
        for path in files:
            body = path.read_text(encoding="utf-8", errors="ignore")
            n = len(PROBLEM.findall(body))
            a = len(ANSWER.findall(body))
            problems += n
            answers += a
            if int(year_dir.name) >= 2012:
                in_range += n
                in_range_files += 1
        total += problems
        if int(year_dir.name) >= 2012:
            rows.append((year_dir.name, len(files), problems, answers))

    print(f"all years : {total} problems")
    print(f"2012-2026 : {in_range} problems in {in_range_files} files")
    print("\nyear  files  problems  answers")
    for year, files, problems, answers in rows:
        print(f"{year}  {files:4}   {problems:5}     {answers:5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
