"""Import OCR'd mock papers as questions.

A mock paper is a question paper, so — unlike a textbook — its value is the 题, cut into
retrievable items. Two routes exist because the vendor offers two shapes:

* ``cut``   — ``RecognizeEduPaperCut`` returns one block per question. This is the route
              the scanned Gaokao papers already use (``ingestion.ingest``): fragment
              merging, gap detection, question typing and the ``pending_review`` decision
              all come with it.
* ``whole`` — ``RecognizeEduPaperOcr`` returns the whole page as one string. Paragraph
              segmentation then sees one block and finds one question (26 pages produced
              8 questions that way), so the page is sliced at question boundaries first.

``whole`` has **not been measured against a real call yet** — the OCR service expired
before the comparison ran. ``cut`` is the default for that reason.

Provenance: these come from a community file space, not a licensed provider. They are
stored as ``restricted`` with a note saying so: "the user does not care where it came
from" is a decision about risk, not a statement about rights.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ingestion, knowledge_review, taxonomy
from app.services import ocr as ocr_service
from app.services import textbook_import
from app.services.platform_import import PLATFORM_PRINCIPAL, _category

PARSER_VERSION = "mock-ocr-1"
SCHEMA_VERSION = "1.0"

ATTRIBUTION = (
    "笔袋（gaojiua.com）共享空间「官方资料总库/优质模拟」的用户上传文件；"
    "来源与授权状态未能核实，仅作内部教研使用，不得再分发"
)

#: a question starts when a number follows a sentence end (or the page start). Matching
#: any digit would split inside formulas such as `f(2).`
_NUM_START = re.compile(r"(?:(?<=[。；;！？?!）)】\]}])|\A)\s*(\d{1,3})\s*[.、．]")
_PAREN_START = re.compile(r"(?:(?<=[。；;！？?!）)】\]}])|\A)\s*[（(]\s*(\d{1,3})\s*[)）]")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def blocks_from_page_text(text: str, start_index: int) -> tuple[list[ingestion.Block], int]:
    """Slice a page's continuous OCR text at question boundaries."""
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


async def already_imported(session: AsyncSession, checksum: str) -> uuid.UUID | None:
    return (
        await session.execute(
            text(
                """
                SELECT v.id FROM knowledge_document_versions v
                JOIN knowledge_sources s ON s.id = v.source_id
                WHERE s.scope = 'platform' AND v.checksum_sha256 = :c LIMIT 1
                """
            ),
            {"c": checksum},
        )
    ).scalar()


async def _persist_segments(
    session: AsyncSession, version_id: uuid.UUID, segments: list[ingestion.Segment]
) -> dict[str, Any]:
    """Write segments as chunks, and the numbered ones as questions."""
    chunks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for item in segments:
        locator: dict[str, Any] = {"ocr": "whole-page", "segment": item.ordinal}
        if item.locator and "paragraph_start" in item.locator:
            locator["block_start"] = item.locator["paragraph_start"]
        chunks.append(
            {
                "id": uuid.uuid4(),
                "key": f"s{item.ordinal:04d}",
                "ordinal": item.ordinal,
                "body": item.text,
                "hash": _hash(item.text),
                "locator": json.dumps(locator, sort_keys=True),
            }
        )
        if item.question_no:
            points = taxonomy.tag(item.text)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "no": str(item.question_no),
                    "ordinal": item.ordinal,
                    "stem_locator": json.dumps(locator, sort_keys=True),
                    "qtype": item.question_type or ingestion.classify(item.section, item.text),
                    "points": points or None,
                }
            )

    if chunks:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_chunks
                    (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                     locator, content_kind, parser_version, parse_schema_version)
                VALUES (:id, :v, :key, :ordinal, :body, :hash, CAST(:locator AS jsonb),
                        'text', :parser, :schema)
                """
            ),
            [
                {**chunk, "v": version_id, "parser": PARSER_VERSION, "schema": SCHEMA_VERSION}
                for chunk in chunks
            ],
        )
    if rows:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_questions
                    (id, document_version_id, question_no, section_label, ordinal,
                     stem_locator, answer_locator, current_paper_question_type,
                     current_knowledge_points, segmentation_status, segmentation_source)
                VALUES (:id, :v, :no, NULL, :ordinal, CAST(:stem_locator AS jsonb), NULL,
                        :qtype, CAST(:points AS text[]), 'accepted', 'rule')
                """
            ),
            [{**row, "v": version_id} for row in rows],
        )
    return {"chunks": len(chunks), "questions": len(rows)}


async def _record_run(
    session: AsyncSession, version_id: uuid.UUID, *, action: str, metrics: dict[str, Any]
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO knowledge_ingestion_runs
                (id, document_version_id, stage, status, tool_version, started_at,
                 finished_at, metrics)
            VALUES (gen_random_uuid(), :v, 'ocr', 'succeeded', :tool, now(), now(),
                    CAST(:metrics AS jsonb))
            """
        ),
        {
            "v": version_id,
            "tool": PARSER_VERSION,
            "metrics": json.dumps(
                {"engine": "aliyun", "action": action, **metrics}, ensure_ascii=False
            ),
        },
    )


async def _ingest_whole(
    session: AsyncSession, version_id: uuid.UUID, raw: bytes, max_pages: int
) -> dict[str, Any]:
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
    written = await _persist_segments(session, version_id, segments)
    await _record_run(
        session,
        version_id,
        action="RecognizeEduPaperOcr",
        metrics={"pages": len(images), **written},
    )
    await session.execute(
        text(
            "UPDATE knowledge_document_versions SET lifecycle_status = 'indexed', "
            "indexed_at = now() WHERE id = :v"
        ),
        {"v": version_id},
    )
    return {
        "status": "indexed",
        "questions": written["questions"],
        "chunks": written["chunks"],
        "ocr": {"pages": len(images)},
    }


async def import_mock_paper(
    session: AsyncSession,
    *,
    path: Path,
    title: str,
    max_pages: int = 0,
    accept: bool = True,
    route: str = "cut",
) -> dict[str, Any]:
    """Import one mock paper. `route` selects the OCR shape; see the module docstring."""
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    existing = await already_imported(session, checksum)
    if existing:
        return {"skipped": True, "document_version_id": str(existing), "title": title}

    category_id = await _category(session, "mock_exam")
    source_id = uuid.uuid4()
    version_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by, rights_note)
            VALUES (:id, 'platform', NULL, :category, 'mock_exam', :title, 'restricted',
                    'classroom', :principal, :note)
            """
        ),
        {
            "id": source_id,
            "category": category_id,
            "title": title,
            "principal": PLATFORM_PRINCIPAL,
            "note": ATTRIBUTION,
        },
    )

    storage_key = f"uploads/{source_id}/{version_id}.pdf"
    destination = Path(ingestion.UPLOAD_ROOT) / storage_key.split("uploads/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by)
            VALUES (:id, :source, 1, :key, :hash, 'application/pdf', :size,
                    'processing', :principal)
            """
        ),
        {
            "id": version_id,
            "source": source_id,
            "key": storage_key,
            "hash": checksum,
            "size": len(raw),
            "principal": PLATFORM_PRINCIPAL,
        },
    )

    if route == "whole":
        parsed = await _ingest_whole(session, version_id, raw, max_pages)
    else:
        parsed = await ingestion.ingest(session, PLATFORM_PRINCIPAL, version_id)
        if accept and parsed.get("status") == "pending_review":
            await knowledge_review.promote(session, PLATFORM_PRINCIPAL, version_id)

    return {
        "skipped": False,
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": title,
        "pages": (parsed.get("ocr") or {}).get("pages", 0),
        "questions": parsed.get("questions", 0),
        "segments": parsed.get("chunks", parsed.get("questions", 0)),
        "numbers": (parsed.get("ocr") or {}).get("gaps", []),
        "status": parsed.get("status"),
    }
