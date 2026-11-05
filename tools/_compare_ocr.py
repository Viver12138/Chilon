"""Compare the two OCR routes on one paper: paper-cut vs whole-page + segmentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app.services import ingestion, ocr as ocr_service, textbook_import  # noqa: E402

# a question starts when a number follows a sentence end or the start of the text
NUM_START = re.compile(r"(?:(?<=[。；;！？?!）)])\s*|\A)\s*(\d{1,3})\s*[.、．]")
PAREN_START = re.compile(r"(?:(?<=[。；;！？?!）)])\s*|\A)\s*[（(]\s*(\d{1,3})\s*[)）]")


def blocks_from_text(text: str, start_index: int) -> tuple[list[ingestion.Block], int]:
    """Slice a page's continuous OCR text at question boundaries."""
    style = "num" if NUM_START.search(text) else "paren"
    pattern = NUM_START if style == "num" else PAREN_START
    starts = [m.start() for m in pattern.finditer(text)]
    if not starts:
        return [ingestion.Block(index=start_index, text=text.strip())], start_index + 1
    blocks: list[ingestion.Block] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            blocks.append(ingestion.Block(index=start_index, text=chunk))
            start_index += 1
    return blocks, start_index


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "江西六校"
    path = next((ROOT / "corpus/mock-exams").glob(f"*{name}*数学试题.pdf"))
    pages = ocr_service.render_pages(path.read_bytes())
    print(f"{path.name[:50]} pages={len(pages)}")

    blocks: list[ingestion.Block] = []
    index = 0
    for number, image in enumerate(pages, 1):
        body = textbook_import.call_whole_page(image)
        page_blocks, index = blocks_from_text(body, index)
        for block in page_blocks:
            block.page = number
        blocks.extend(page_blocks)
        print(f"  page {number}: {len(body)} chars -> {len(page_blocks)} blocks")

    segments = ingestion.segment(blocks)
    questions = [item for item in segments if item.question_no]
    print(f"\nblocks={len(blocks)} segments={len(segments)} questions={len(questions)}")
    numbers = [item.question_no for item in questions]
    print("numbers:", numbers)
    for item in questions[:3]:
        print("\n---", item.question_no, (item.text or "")[:180].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
