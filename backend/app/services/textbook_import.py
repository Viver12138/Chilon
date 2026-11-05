"""Import textbooks into the platform corpus.

Textbooks are not question papers, and the pipeline says so in three places:

* **A different OCR action.** `RecognizeEduPaperCut` returns only 例题/习题 blocks; the
  explanations between them — the reason a textbook exists — are discarded. On a prose
  page it returned 3 blocks and dropped the paragraph that defines 补集.
  `RecognizeEduPaperOcr` returns the whole page in one `content` string, which is what
  gets stored.
* **No question rows.** `segment()` would turn "例5"/"1." into fake questions. A textbook
  is prose; it becomes chunks, and retrieval finds passages.
* **`restricted`, not `licensed`.** The content is 人民教育出版社's; the GitHub upload
  claims Apache-2.0 over material it cannot license. Marking it `licensed` would be a
  false statement in the data.
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

from app.services import aliyun_ocr, ocr as ocr_service
from app.services.platform_import import PLATFORM_PRINCIPAL, _category

WHOLE_PAGE_ACTION = "RecognizeEduPaperOcr"
PARSER_VERSION = "textbook-ocr-1"
SCHEMA_VERSION = "1.0"
CHUNK_TARGET = 600

ATTRIBUTION = (
    "人民教育出版社《普通高中教科书·数学（A版）》电子版，著作权归人民教育出版社；"
    "来源 github.com/litongjava/china_high_school_math_people_teach_a_version_pdf "
    "（该仓库的 Apache-2.0 标注不适用于教材内容本身）"
)

SENTENCE_END = re.compile(r"(?<=[。！？；])")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def call_whole_page(image: bytes) -> str:
    """One page → its full text, including the prose the paper-cut action drops."""
    import httpx

    from app import settings as config

    settings = config.load()
    params = {"ImageType": "scan", "Subject": "Math"}
    headers = aliyun_ocr.sign_request(
        access_key_id=settings.ocr_aliyun_key_id,
        access_key_secret=settings.ocr_aliyun_key_secret,
        action=WHOLE_PAGE_ACTION,
        params=params,
        body=image,
        timestamp=aliyun_ocr.now_timestamp(),
    )
    url = f"https://{aliyun_ocr.OCR_HOST}/?{aliyun_ocr.canonical_query(params)}"
    response = httpx.post(url, headers=headers, content=image, timeout=120, follow_redirects=True)
    if response.status_code != 200:
        raise RuntimeError(
            f"whole-page OCR returned {response.status_code}: {response.text[:200]}"
        )
    data = aliyun_ocr.decode_data(response.json())
    body = (data.get("content") or "").strip()
    return body


def split_page(body: str) -> list[str]:
    """Split a page into passage-sized pieces, never mid-sentence."""
    body = re.sub(r"\n{2,}", "\n", body).strip()
    if not body:
        return []
    pieces: list[str] = []
    buffer = ""
    for sentence in SENTENCE_END.split(body):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(buffer) + len(sentence) > CHUNK_TARGET and buffer:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer}{sentence}" if buffer else sentence
    if buffer:
        pieces.append(buffer)
    return [piece for piece in pieces if len(piece) >= 40]


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


async def import_textbook(
    session: AsyncSession,
    *,
    path: Path,
    title: str,
    max_pages: int = 0,
) -> dict[str, Any]:
    """Import one textbook PDF. Runs OCR page by page; every page costs a call."""
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    existing = await already_imported(session, checksum)
    if existing:
        return {"skipped": True, "document_version_id": str(existing), "title": title}

    category_id = await _category(session, "textbook")
    source_id = uuid.uuid4()
    version_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by, rights_note)
            VALUES (:id, 'platform', NULL, :category, 'textbook', :title, 'restricted',
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
    destination = Path(ocr_service.__file__).resolve().parents[2] / "var" / storage_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by, indexed_at)
            VALUES (:id, :source, 1, :key, :hash, 'application/pdf', :size,
                    'indexed', :principal, now())
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

    pages = ocr_service.render_pages(raw)
    if max_pages:
        pages = pages[:max_pages]

    chunks: list[dict[str, Any]] = []
    ordinal = 0
    for page_number, image in enumerate(pages, 1):
        body = call_whole_page(image)
        for part, piece in enumerate(split_page(body), 1):
            ordinal += 1
            locator = {"ocr_action": WHOLE_PAGE_ACTION, "page": page_number, "part": part}
            chunks.append(
                {
                    "id": uuid.uuid4(),
                    "key": f"p{page_number:04d}-{part:02d}",
                    "ordinal": ordinal,
                    "body": piece,
                    "hash": _hash(piece),
                    "locator": json.dumps(locator, sort_keys=True),
                    "page": page_number,
                }
            )

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
        [{**chunk, "v": version_id, "parser": PARSER_VERSION, "schema": SCHEMA_VERSION} for chunk in chunks],
    )

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
                {
                    "engine": "aliyun",
                    "action": WHOLE_PAGE_ACTION,
                    "pages_ocr": len(pages),
                    "chunks": len(chunks),
                },
                ensure_ascii=False,
            ),
        },
    )

    return {
        "skipped": False,
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": title,
        "pages": len(pages),
        "chunks": len(chunks),
    }
