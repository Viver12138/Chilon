"""Add the whole-page route to mock_import, and the page slicer it needs."""

from __future__ import annotations

import pathlib

p = pathlib.Path("D:/Chilon/backend/app/services/mock_import.py")
s = p.read_text(encoding="utf-8")

helper = '''

#: A question starts when a number follows a sentence end (or the page start). Plain
#: "any digit" would split inside formulas such as `f(2).`
_NUM_START = __import__("re").compile(r"(?:(?<=[。；;！？?!）)])\\s*|\\A)\\s*(\\d{1,3})\\s*[.、．]")
_PAREN_START = __import__("re").compile(r"(?:(?<=[。；;！？?!）)])\\s*|\\A)\\s*[（(]\\s*(\\d{1,3})\\s*[)）]")


def blocks_from_page_text(text: str, start_index: int) -> tuple[list[ingestion.Block], int]:
    """Slice a page's continuous OCR text at question boundaries.

    Whole-page OCR returns one long string per page; paragraph segmentation then sees a
    single block and finds a single question (26 pages produced 8 questions this way).
    Slicing first, then letting `segment()` do its job, is the alternative route.
    """
    text = (text or "").strip()
    if not text:
        return [], start_index
    pattern = _NUM_START if _NUM_START.search(text) else _PAREN_START
    starts = [match.start() for match in pattern.finditer(text)]
    if not starts:
        return [ingestion.Block(index=start_index, text=text)], start_index + 1

    blocks: list[ingestion.Block] = []
    index = start_index
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(text)
        piece = text[start:end].strip()
        if piece:
            blocks.append(ingestion.Block(index=index, text=piece))
            index += 1
    return blocks, index

'''

anchor = "async def already_imported("
s = s.replace(anchor, helper.strip("\n") + "\n\n\n" + anchor, 1)

# route parameter
s = s.replace(
    '''    max_pages: int = 0,
    accept: bool = True,
) -> dict[str, Any]:''',
    '''    max_pages: int = 0,
    accept: bool = True,
    route: str = "cut",
) -> dict[str, Any]:''',
)

s = s.replace(
    '''    parsed = await ingestion.ingest(session, PLATFORM_PRINCIPAL, version_id)''',
    '''    parsed = await ingest_with_route(
        session, version_id, raw=raw, route=route, max_pages=max_pages
    )''',
)

# the route implementation lives beside the importer
s = s.replace(
    '''async def import_mock_paper(''',
    '''async def ingest_with_route(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    raw: bytes,
    route: str,
    max_pages: int = 0,
) -> dict[str, Any]:
    """`cut` uses the paper-cut action through ingestion; `whole` reads full pages first."""
    if route != "whole":
        return await ingestion.ingest(session, PLATFORM_PRINCIPAL, version_id)

    images = ocr_service.render_pages(raw)
    if max_pages:
        images = images[:max_pages]
    blocks: list[ingestion.Block] = []
    index = 0
    for page_number, image in enumerate(images, 1):
        body = textbook_import.call_whole_page(image)
        page_blocks, index = blocks_from_page_text(body, index)
        for block in page_blocks:
            block.page = page_number
        blocks.extend(page_blocks)

    segments = ingestion.segment(blocks)
    return {
        "status": "parsed",
        "questions": len([item for item in segments if item.question_no]),
        "chunks": len(segments),
        "segments": segments,
        "ocr": {"engine": "aliyun", "action": "RecognizeEduPaperOcr", "pages": len(images)},
    }


async def import_mock_paper(''',
    1,
)

s = s.replace(
    "from app.services import ingestion, knowledge_review",
    "from app.services import ingestion, knowledge_review, ocr as ocr_service, textbook_import",
)
p.write_text(s, encoding="utf-8", newline="\n")
print("mock_import: whole-page route added")
