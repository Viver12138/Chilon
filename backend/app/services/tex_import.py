"""Import the LaTeX corpus into the platform knowledge base.

Why TeX and not the scanned PDFs: the PDFs' text layer mangles every formula
(`\\cap` comes out as `\\`, `\\sqrt` as `p`), while the TeX source is exact **and carries
the answers**. Measured on 2012-2026: 274 papers, 6050 problems, 4124 with an answer.

What is stored, and what is deliberately not:

* stem + options → one chunk and one question row (retrieval needs both);
* answer → its own chunk (teacher-only content in this product; retrieval may return it,
  which is the same behaviour as the scanned path);
* **solution is not stored.** It is long prose, it would dominate retrieval, and the
  corpus exists to be *found*, not to be read end to end. Recorded as a known gap.
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

from app.services import ingestion, taxonomy, tex_parse
from app.services.platform_import import PLATFORM_PRINCIPAL, _category

TEX_MIME = "application/x-latex"

#: CC BY-SA 4.0 obliges us to name the work and the upstream source in the data itself,
#: not only in a README that a deployment can lose.
ATTRIBUTION = (
    "Gaokao-Math-Problems-Compilation (CC BY-SA 4.0), "
    "https://github.com/DxAThing/Gaokao-Math-Problems-Compilation ; "
    "upstream questions: deekur/gaokaomath (CC BY 4.0)"
)
PARSER_VERSION = "tex-gaokao-1"
SCHEMA_VERSION = "1.0"
YEAR = re.compile(r"(\d{4})")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stem_text(problem: tex_parse.Problem) -> str:
    """Options belong to the stem text: the schema has no options column, and a question
    without its options is not answerable."""
    body = problem.stem
    if problem.options:
        labels = "ABCD"
        rendered = "\n".join(
            f"({labels[i] if i < len(labels) else i + 1}) {option}"
            for i, option in enumerate(problem.options)
        )
        body = f"{body}\n{rendered}"
    return body


async def already_imported(session: AsyncSession, checksum: str) -> uuid.UUID | None:
    return (
        await session.execute(
            text(
                """
                SELECT v.id FROM knowledge_document_versions v
                JOIN knowledge_sources s ON s.id = v.source_id
                WHERE s.scope = 'platform' AND v.checksum_sha256 = :c
                LIMIT 1
                """
            ),
            {"c": checksum},
        )
    ).scalar()


async def import_paper(
    session: AsyncSession,
    *,
    path: Path,
    base: Path,
    source_type: str = "gaokao_paper",
) -> dict[str, Any]:
    """Import one .tex file as one platform paper."""
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    existing = await already_imported(session, checksum)
    if existing:
        return {"skipped": True, "document_version_id": str(existing), "title": path.stem}

    paper = tex_parse.parse_file(path)
    if not paper.problems:
        return {"skipped": False, "title": paper.title, "problems": 0, "error": "no problems"}

    category_id = await _category(session, source_type)
    source_id = uuid.uuid4()
    version_id = uuid.uuid4()
    year_match = YEAR.search(path.parent.name)
    year = int(year_match.group(1)) if year_match else None

    await session.execute(
        text(
            """
            INSERT INTO knowledge_sources
                (id, scope, owner_id, category_id, source_type, title, rights_status,
                 distribution_scope, created_by, rights_note)
            VALUES (:id, 'platform', NULL, :category, :type, :title, 'licensed',
                    'classroom', :principal, :note)
            """
        ),
        {
            "id": source_id,
            "category": category_id,
            "type": source_type,
            "title": paper.title,
            "principal": PLATFORM_PRINCIPAL,
            "note": ATTRIBUTION,
        },
    )

    storage_key = f"uploads/{source_id}/{version_id}.tex"
    destination = Path(ingestion.UPLOAD_ROOT) / storage_key.split("uploads/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)

    await session.execute(
        text(
            """
            INSERT INTO knowledge_document_versions
                (id, source_id, version_no, storage_key, checksum_sha256, mime_type,
                 file_size_bytes, lifecycle_status, uploaded_by, indexed_at)
            VALUES (:id, :source, 1, :key, :hash, :mime, :size, 'indexed', :principal, now())
            """
        ),
        {
            "id": version_id,
            "source": source_id,
            "key": storage_key,
            "hash": checksum,
            "mime": TEX_MIME,
            "size": len(raw),
            "principal": PLATFORM_PRINCIPAL,
        },
    )

    relative = str(path.relative_to(base)).replace("\\", "/")
    chunks: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    answered = 0
    for problem in paper.problems:
        number = str(problem.ordinal)
        stem_body = _stem_text(problem)
        stem_locator = {"tex": relative, "kind": "stem", "problem": problem.ordinal}
        chunks.append(
            {
                "id": uuid.uuid4(),
                "key": f"q{problem.ordinal:05d}",
                "ordinal": problem.ordinal,
                "body": stem_body,
                "hash": _hash(stem_body),
                "locator": json.dumps(stem_locator, sort_keys=True),
            }
        )
        answer_locator = None
        if problem.answer:
            answer_locator = {"tex": relative, "kind": "answer", "problem": problem.ordinal}
            chunks.append(
                {
                    "id": uuid.uuid4(),
                    "key": f"a{problem.ordinal:05d}",
                    "ordinal": 100000 + problem.ordinal,
                    "body": problem.answer,
                    "hash": _hash(problem.answer),
                    "locator": json.dumps(answer_locator, sort_keys=True),
                }
            )
            answered += 1
        points = taxonomy.tag(stem_body)
        questions.append(
            {
                "id": uuid.uuid4(),
                "no": number,
                "ordinal": problem.ordinal,
                "stem_locator": json.dumps(stem_locator, sort_keys=True),
                "answer_locator": json.dumps(answer_locator, sort_keys=True) if answer_locator else None,
                "qtype": ingestion.classify(problem.section, stem_body),
                "points": points or None,
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
        [
            {
                **chunk,
                "v": version_id,
                "parser": PARSER_VERSION,
                "schema": SCHEMA_VERSION,
            }
            for chunk in chunks
        ],
    )
    await session.execute(
        text(
            """
            INSERT INTO knowledge_questions
                (id, document_version_id, question_no, section_label, ordinal, stem_locator,
                 answer_locator, current_paper_question_type, current_knowledge_points,
                 segmentation_status, segmentation_source)
            VALUES (:id, :v, :no, NULL, :ordinal, CAST(:stem_locator AS jsonb),
                    CAST(:answer_locator AS jsonb), :qtype, CAST(:points AS text[]),
                    'accepted', 'rule')
            """
        ),
        [{**question, "v": version_id} for question in questions],
    )

    await session.execute(
        text(
            """
            INSERT INTO knowledge_ingestion_runs
                (id, document_version_id, stage, status, tool_version,
                 started_at, finished_at, metrics)
            VALUES (gen_random_uuid(), :v, 'parse', 'succeeded', :tool, now(), now(),
                    CAST(:metrics AS jsonb))
            """
        ),
        {
            "v": version_id,
            "tool": PARSER_VERSION,
            "metrics": json.dumps(
                {
                    "engine": "tex",
                    "year": year,
                    "problems": len(paper.problems),
                    "answered": answered,
                    "source": relative,
                },
                ensure_ascii=False,
            ),
        },
    )

    return {
        "skipped": False,
        "source_id": str(source_id),
        "document_version_id": str(version_id),
        "title": paper.title,
        "problems": len(paper.problems),
        "answered": answered,
    }
