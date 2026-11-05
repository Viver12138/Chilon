"""Measure the downloaded corpus: pages, text layers, and the OCR bill if any."""

from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path("D:/Chilon/var/_gaokao_clone/repo/普通高考")


def main() -> int:
    files = sorted(ROOT.rglob("*.pdf"))
    total_pages = text_pages = scanned_pages = 0
    no_text_files = 0
    broken: list[str] = []
    per_year: dict[str, list[int]] = {}

    for path in files:
        year = path.parent.name
        try:
            reader = PdfReader(str(path))
            pages = len(reader.pages)
        except Exception:  # noqa: BLE001
            broken.append(path.name)
            continue
        with_text = 0
        for page in reader.pages:
            try:
                body = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001
                body = ""
            if len(body) >= 40:
                with_text += 1
        total_pages += pages
        text_pages += with_text
        scanned_pages += pages - with_text
        if with_text == 0:
            no_text_files += 1
        stat = per_year.setdefault(year, [0, 0, 0])
        stat[0] += 1
        stat[1] += pages
        stat[2] += pages - with_text

    print(f"files          : {len(files)}  (broken: {len(broken)})")
    print(f"pages          : {total_pages}")
    print(f"with text layer: {text_pages}")
    print(f"need OCR       : {scanned_pages}  <- billable pages")
    print(f"files with no text at all: {no_text_files}")
    if broken:
        print("broken:", broken[:5])
    print("\nper year: files / pages / ocr pages")
    for year in sorted(per_year):
        files_n, pages_n, ocr_n = per_year[year]
        print(f"  {year}  {files_n:3}  {pages_n:4}  {ocr_n:4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
