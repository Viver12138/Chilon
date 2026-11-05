"""Ingestion: an uploaded paper becomes chunks and questions that retrieval can find.

The join in `knowledge_search` is `q.stem_locator = c.locator`, so the segmentation
rule is forced by the retrieval design: **one question per chunk**, and the question's
`stem_locator` is literally the chunk's `locator`. A chunk holding three questions
would fan the join out and return duplicated rows, so the split happens before
anything is written.

Deterministic only. No model decides where a question starts: a paper that is
segmented slightly wrong is recoverable by re-ingesting, but a paper segmented by an
LLM cannot be re-derived or diffed. Rule-based, versioned, repeatable.

**Generating is not verifying.** This module proves it read the file and found
questions; it does not claim the questions are the right ones. `segmentation_source`
is `rule` and `segmentation_status` is `auto` so a later review can find every
guess.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import taxonomy

PARSER_VERSION = "chilon-ingest-1"
PARSE_SCHEMA_VERSION = "1.0"

UPLOAD_ROOT = Path(os.environ.get("CHILON_UPLOAD_DIR", "var/uploads"))

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"

# 1. 1、 1． (1) 一、 — the shapes a Chinese exam paper actually uses
QUESTION_START = re.compile(
    r"^\s*(?:"
    r"(?P<num>\d{1,3})\s*[.、．]"          # 1.  1、  1．
    r"|[(（]\s*(?P<paren>\d{1,3})\s*[)）]"  # (1)  （1）
    r")"
)
SECTION_START = re.compile(r"^\s*(?:一|二|三|四|五|六|七|八|九|十)\s*[、.]")

# a trailing answer key: the heading, then `1. A` lines
ANSWER_KEY_HEADING = re.compile(r"^\s*(?:参考答案|答案与解析|答案|解析)\s*[:：]?\s*$")
KEY_ENTRY = re.compile(r"^\s*(?P<no>\d{1,3})\s*[.、．]\s*(?P<ans>\S.*?)\s*$")

# an answer stated inside the question
INLINE_ANSWER = re.compile(
    r"^\s*(?:【答案】|【解析】|【解答】|答案\s*[:：]|解析\s*[:：]|答\s*[:：]"
    r"|Answer\s*[:：]|Ans\s*[:：]|Solution\s*[:：])",
    re.IGNORECASE,
)

# options, as a paper prints them: A. / A、 / A）
OPTION = re.compile(r"(?:^|\s)[A-D]\s*[.、．)）]\s*\S")
BLANK = re.compile(r"_{3,}|＿{2,}|[（(]\s{2,}[)）]|（\s*）|\(\s*\)")
MULTI_HINT = re.compile(r"多选|至少有一项|有多项符合|正确的有|不正确的有")
SECTION_SINGLE = re.compile(r"选择")
SECTION_MULTI = re.compile(r"多选|多项选择")
SECTION_FILL = re.compile(r"填空")
SECTION_FREE = re.compile(r"解答|计算|证明|综合")

QUESTION_TYPES = ("single_choice", "multiple_choice", "fill_blank", "free_response")


class IngestionError(Exception):
    pass


class UnsupportedFormat(IngestionError):
    """No extractor for this file type, or the file is not what it claims to be."""


@dataclass(frozen=True)
class Block:
    index: int
    text: str
    page: int | None = None


# ── extraction ─────────────────────────────────────────────────────────────────

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx_paragraphs(data: bytes) -> list[Block]:
    """Read `word/document.xml` and return one entry per paragraph."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnsupportedFormat(f"not a readable DOCX: {exc}") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise UnsupportedFormat(f"document.xml is not valid XML: {exc}") from exc

    blocks: list[Block] = []
    for paragraph in root.iter(f"{_W}p"):
        pieces = [
            node.text or "" for node in paragraph.iter(f"{_W}t")
        ]
        raw = "".join(pieces).strip()
        if raw:
            blocks.append(Block(len(blocks), raw))
    return blocks


def extract_pdf_blocks(data: bytes) -> list[Block]:
    """Read a PDF's text layer, one block per non-empty line.

    Scanned papers have no text layer. Returning an empty list would look like "a
    parseable document with nothing in it", so that case is refused with the reason and
    the alternative — OCR is not implemented, and pretending otherwise would let a
    teacher upload a scan and silently get an empty knowledge base.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pypdf raises several unrelated types
        raise UnsupportedFormat(
            f"无法读取的 PDF（{exc}）；请上传可复制文字的 PDF 或 .docx"
        ) from exc

    blocks: list[Block] = []
    for page_number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one broken page must not lose the rest
            text = ""
        for line in (raw.strip() for raw in text.splitlines()):
            if line:
                blocks.append(Block(len(blocks), line, page_number))

    if not blocks:
        raise UnsupportedFormat(
            "这个 PDF 没有文字层（可能是扫描件或拍照件），需要 OCR 才能解析；"
            "请上传可复制文字的 PDF，或先把文件另存为 .docx"
        )
    return blocks


def paragraphs_for(mime: str, data: bytes) -> list[Block]:
    if mime == DOCX_MIME:
        return extract_docx_paragraphs(data)
    if mime == PDF_MIME:
        return extract_pdf_blocks(data)
    raise UnsupportedFormat(f"unsupported mime type {mime!r}")


# ── classification ─────────────────────────────────────────────────────────────


def classify(section: str | None, text: str) -> str | None:
    """Decide the paper question type, or return None when it cannot be decided.

    The section heading is the strongest signal a paper gives ("一、选择题" is a
    promise about every question under it), so it is tried first; content is the
    fallback. **When neither is conclusive the answer is None**, not a default: an
    invented type would flow into scoring and formatting decisions that nobody
    checked.
    """
    label = section or ""
    if SECTION_MULTI.search(label):
        return "multiple_choice"
    if SECTION_FILL.search(label):
        return "fill_blank"
    if SECTION_FREE.search(label):
        return "free_response"
    if SECTION_SINGLE.search(label):
        # a section named 选择题 can still contain multi-select items; the stem's own
        # wording is more specific than the section heading, so it wins here
        return "multiple_choice" if MULTI_HINT.search(text) else "single_choice"

    if len(OPTION.findall(text)) >= 2:
        return "multiple_choice" if MULTI_HINT.search(text) else "single_choice"
    if BLANK.search(text):
        return "fill_blank"
    return None


# ── segmentation ───────────────────────────────────────────────────────────────


@dataclass
class Segment:
    ordinal: int
    question_no: str | None
    section: str | None
    locator: dict[str, Any]
    text: str
    answer_locator: dict[str, Any] | None = None
    answer_text: str | None = None
    question_type: str | None = None


def segment(blocks: list[Block]) -> list[Segment]:
    """Split paragraphs into one segment per question, or per run of prose.

    Answers are extracted, not left inside the stem, for two reasons:

    1. the stem is what retrieval matches on, and an answer line dilutes it;
    2. the answer is *teacher-only* content. Keeping it in its own chunk with its own
       locator is what lets a later step project it out instead of hoping a renderer
       hides it.

    Three shapes are recognised, all deterministic:
    `答案：…` inline, `【答案】…` inline, and a trailing key section
    (`参考答案` followed by `1. A` lines) matched back by question number.
    """
    segments: list[Segment] = []
    section: str | None = None
    current: list[Block] = []
    answer_blocks: list[Block] = []
    current_no: str | None = None
    key_mode = False
    key_answers: dict[str, tuple[int, str]] = {}

    def flush() -> None:
        nonlocal current, answer_blocks, current_no
        if not current:
            return
        stem = "\n".join(b.text for b in current).strip()
        answer = "\n".join(b.text for b in answer_blocks).strip()
        if stem:
            segments.append(
                Segment(
                    ordinal=len(segments),
                    question_no=current_no,
                    section=section,
                    locator=locator_for(current),
                    text=stem,
                    answer_locator=locator_for(answer_blocks) if answer_blocks else None,
                    answer_text=answer or None,
                    question_type=classify(section, stem) if current_no else None,
                )
            )
        current = []
        answer_blocks = []
        current_no = None

    for block in blocks:
        if ANSWER_KEY_HEADING.match(block.text):
            flush()
            key_mode = True
            continue
        if key_mode:
            entry = KEY_ENTRY.match(block.text)
            if entry:
                key_answers[entry.group("no")] = (block.index, entry.group("ans").strip())
            continue
        if SECTION_START.match(block.text):
            flush()
            section = block.text.strip()[:60]
            continue
        match = QUESTION_START.match(block.text)
        if match:
            flush()
            current_no = match.group("num") or match.group("paren")
            current.append(block)
            continue
        if INLINE_ANSWER.match(block.text):
            # the answer starts here; everything after it belongs to the answer
            answer_blocks.append(block)
            continue
        if answer_blocks:
            answer_blocks.append(block)
            continue
        current.append(block)
    flush()

    # a trailing key fills in the questions that carried no inline answer
    for item in segments:
        if item.question_no and item.answer_text is None and item.question_no in key_answers:
            index, value = key_answers[item.question_no]
            item.answer_text = value
            item.answer_locator = {"paragraph_start": index, "paragraph_end": index}
    return segments


def locator_for(blocks: list[Block]) -> dict[str, Any]:
    location: dict[str, Any] = {
        "paragraph_start": blocks[0].index,
        "paragraph_end": blocks[-1].index,
    }
    if blocks[0].page is not None:
        location["page_number"] = blocks[0].page
    return location


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stem_key(segment: Segment) -> str:
    return f"p{segment.locator['paragraph_start']:05d}"


def answer_key(segment: Segment) -> str:
    locator = segment.answer_locator or {}
    return f"a{locator.get('paragraph_start', 0):05d}"


# ── ingestion ──────────────────────────────────────────────────────────────────


async def _record_run(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    status: str,
    metrics: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO knowledge_ingestion_runs
                (id, document_version_id, stage, status, tool_version,
                 started_at, finished_at, error_code, error_detail, metrics)
            VALUES
                (gen_random_uuid(), :v, 'parse', :status, :tool,
                 now(), now(), :code, :detail, CAST(:metrics AS jsonb))
            """
        ),
        {
            "v": version_id,
            "status": status,
            "tool": PARSER_VERSION,
            "code": error_code,
            "detail": error_detail,
            "metrics": json.dumps(metrics or {}, ensure_ascii=False),
        },
    )



async def _mark_failed(session: AsyncSession, version_id: uuid.UUID) -> None:
    """Record the failure on the version itself.

    `failed` is a declared lifecycle state. Leaving the row in `processing` would make
    a permanently broken upload indistinguishable from one still being parsed.
    """
    await session.execute(
        text("UPDATE knowledge_document_versions SET lifecycle_status = 'failed' WHERE id = :v"),
        {"v": version_id},
    )


async def ingest(
    session: AsyncSession, owner_id: uuid.UUID, document_version_id: uuid.UUID
) -> dict[str, Any]:
    """Parse one document version into chunks and questions.

    Returns a summary either way. On failure the version stays `processing` and the
    reason is recorded on the run row — a version marked `indexed` with nothing behind
    it would let retrieval quietly return zero while looking healthy.
    """
    version = (
        await session.execute(
            text(
                """
                SELECT id, source_id, storage_key, mime_type, lifecycle_status
                FROM knowledge_document_versions WHERE id = :id
                """
            ),
            {"id": document_version_id},
        )
    ).first()
    if version is None:
        raise IngestionError("document version not found")

    # storage_key is 'uploads/<source>/<version>.docx' and UPLOAD_ROOT already ends in
    # 'uploads', so the prefix is stripped rather than resolved against the root twice
    relative = version.storage_key.split("uploads/", 1)[-1]
    path = UPLOAD_ROOT / relative
    if not path.exists():
        await _record_run(
            session,
            document_version_id,
            status="failed",
            error_code="file_missing",
            error_detail=f"storage has no file at {path}",
        )
        await _mark_failed(session, document_version_id)
        return {"status": "failed", "error": "file_missing", "chunks": 0, "questions": 0}

    data = path.read_bytes()
    try:
        blocks = paragraphs_for(version.mime_type, data)
        segments = segment(blocks)
    except UnsupportedFormat as exc:
        await _record_run(
            session,
            document_version_id,
            status="failed",
            error_code="unsupported_format",
            error_detail=str(exc),
        )
        await _mark_failed(session, document_version_id)
        return {"status": "failed", "error": "unsupported_format", "detail": str(exc),
                "chunks": 0, "questions": 0}

    if not segments:
        await _record_run(
            session,
            document_version_id,
            status="failed",
            error_code="no_text",
            error_detail="the document produced no text",
        )
        await _mark_failed(session, document_version_id)
        return {"status": "failed", "error": "no_text", "chunks": 0, "questions": 0}

    # re-ingest replaces, never appends: two copies of every chunk would double every
    # retrieval result and look like a coverage improvement
    await session.execute(
        text("DELETE FROM knowledge_questions WHERE document_version_id = :v"),
        {"v": document_version_id},
    )
    await session.execute(
        text("DELETE FROM knowledge_chunks WHERE document_version_id = :v"),
        {"v": document_version_id},
    )

    question_count = 0
    answer_count = 0
    for item in segments:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_chunks
                    (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                     locator, content_kind, parser_version, parse_schema_version)
                VALUES
                    (gen_random_uuid(), :v, :key, :ordinal, :body, :hash,
                     CAST(:locator AS jsonb), 'text', :parser, :schema)
                """
            ),
            {
                "v": document_version_id,
                "key": stem_key(item),
                "ordinal": item.ordinal,
                "body": item.text,
                "hash": text_hash(item.text),
                "locator": json.dumps(item.locator, sort_keys=True),
                "parser": PARSER_VERSION,
                "schema": PARSE_SCHEMA_VERSION,
            },
        )

        # The answer lives in its own chunk with its own locator. That is what makes
        # it projectable: a viewer can leave it out by not following answer_locator,
        # instead of a renderer having to guess which line is the answer.
        answer_locator_json: str | None = None
        if item.answer_text and item.answer_locator:
            answer_locator_json = json.dumps(item.answer_locator, sort_keys=True)
            answer_count += 1
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunks
                        (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                         locator, content_kind, parser_version, parse_schema_version)
                    VALUES
                        (gen_random_uuid(), :v, :key, :ordinal, :body, :hash,
                         CAST(:locator AS jsonb), 'text', :parser, :schema)
                    """
                ),
                {
                    "v": document_version_id,
                    "key": answer_key(item),
                    "ordinal": item.ordinal + 10000,
                    "body": item.answer_text,
                    "hash": text_hash(item.answer_text),
                    "locator": answer_locator_json,
                    "parser": PARSER_VERSION,
                    "schema": PARSE_SCHEMA_VERSION,
                },
            )

        if item.question_no:
            question_count += 1
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_questions
                        (id, document_version_id, question_no, section_label, ordinal,
                         stem_locator, answer_locator, current_paper_question_type,
                         current_knowledge_points, segmentation_status, segmentation_source)
                    VALUES
                        (gen_random_uuid(), :v, :no, :section, :ordinal,
                         CAST(:locator AS jsonb), CAST(:answer_locator AS jsonb), :qtype,
                         CAST(:points AS text[]), 'auto', 'rule')
                    """
                ),
                {
                    "v": document_version_id,
                    "no": item.question_no,
                    "section": item.section,
                    "ordinal": item.ordinal,
                    "locator": json.dumps(item.locator, sort_keys=True),
                    "answer_locator": answer_locator_json,
                    "qtype": item.question_type,
                    "points": taxonomy.tag(item.text) or None,
                },
            )

    await session.execute(
        text(
            """
            UPDATE knowledge_document_versions
            SET lifecycle_status = 'indexed', indexed_at = now(),
                parser_version = :parser, parse_schema_version = :schema
            WHERE id = :v
            """
        ),
        {"v": document_version_id, "parser": PARSER_VERSION, "schema": PARSE_SCHEMA_VERSION},
    )

    metrics = {
        "paragraphs": len(blocks),
        "chunks": len(segments) + answer_count,
        "questions": question_count,
        "answers": answer_count,
        "characters": sum(len(s.text) for s in segments),
    }
    await _record_run(session, document_version_id, status="succeeded", metrics=metrics)

    return {
        "status": "indexed",
        "document_version_id": str(document_version_id),
        "chunks": len(segments) + answer_count,
        "questions": question_count,
        "answers": answer_count,
        "source_id": str(version.source_id),
        **metrics,
    }


async def ingest_latest(
    session: AsyncSession, owner_id: uuid.UUID, source_id: uuid.UUID
) -> dict[str, Any]:
    version_id = (
        await session.execute(
            text(
                """
                SELECT id FROM knowledge_document_versions
                WHERE source_id = :s ORDER BY version_no DESC LIMIT 1
                """
            ),
            {"s": source_id},
        )
    ).scalar()
    if version_id is None:
        raise IngestionError("source has no document version")
    return await ingest(session, owner_id, version_id)
