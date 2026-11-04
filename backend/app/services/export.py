"""Export: render a version into a file, one projection per audience.

The DOCX writer is hand-rolled on purpose. DOCX is a zip of XML, and pulling a
library in would add a dependency to the one path that decides whether answers leak.
Writing the XML here means the student file contains only the blocks the student
projection kept — there is no second renderer that could disagree.

The test then unzips the produced file and greps its text, which is the only proof
that matters: **the answer is not in the file.**
"""

from __future__ import annotations

import hashlib
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox import dispatcher
from app.services import materials

EXPORT_ROOT = Path("var/exports")


class ExportError(Exception):
    pass


# ── minimal DOCX writer ─────────────────────────────────────────────────────────

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_HEAD = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>"""
_DOC_TAIL = "<w:sectPr/></w:body></w:document>"


def _paragraph(text_value: str, *, bold: bool = False, size: int | None = None) -> str:
    run_props = []
    if bold:
        run_props.append("<w:b/>")
    if size:
        run_props.append(f'<w:sz w:val="{size}"/>')
    props = f"<w:rPr>{''.join(run_props)}</w:rPr>" if run_props else ""
    body = escape(text_value).replace("\n", "</w:t></w:r></w:p><w:p><w:r><w:t>")
    return f'<w:p><w:r>{props}<w:t xml:space="preserve">{body}</w:t></w:r></w:p>'


def _walk(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        kind = node.get("type")
        if kind in ("section",):
            title = "".join(t.get("value", "") for t in (node.get("title") or []))
            if title:
                out.append(_paragraph(title, bold=True, size=32))
        elif kind in ("paragraph", "answer", "solution", "formula"):
            text = "".join(t.get("value", "") for t in (node.get("content") or []))
            if text:
                out.append(_paragraph(text))
        elif kind == "exercise":
            number = node.get("number")
            prefix = f"{number}. " if number else ""
            first = True
            for child in node.get("blocks") or []:
                if first and child.get("type") == "paragraph":
                    text = "".join(t.get("value", "") for t in (child.get("content") or []))
                    out.append(_paragraph(prefix + text))
                    first = False
                    continue
                _walk(child, out)
            return
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out)


def render_docx(document: dict[str, Any], profile: str) -> bytes:
    """Render one projection to DOCX bytes.

    `profile` is applied here again (not only by the caller) so a caller cannot
    accidentally render a teacher projection into a student file by skipping the
    projection step.
    """
    projected = materials.project(document, profile)

    body: list[str] = []
    metadata = projected.get("metadata") or {}
    title = metadata.get("title") or "未命名材料"
    body.append(_paragraph(title, bold=True, size=40))
    body.append(_paragraph("教师版（含答案）" if profile == "teacher" else "学生版", size=20))
    for block in projected.get("blocks") or []:
        _walk(block, body)

    xml = _DOC_HEAD + "".join(body) + _DOC_TAIL
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def docx_text(data: bytes) -> str:
    """Extract the visible text, so a test can assert what is physically present."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    out = []
    while "<w:t" in xml:
        start = xml.index("<w:t")
        start = xml.index(">", start) + 1
        end = xml.index("</w:t>", start)
        out.append(xml[start:end])
        xml = xml[end + len("</w:t>") :]
    return "\n".join(out)


# ── export records ──────────────────────────────────────────────────────────────


async def create_export(
    session: AsyncSession,
    owner_id: uuid.UUID,
    material_version_id: uuid.UUID,
    *,
    profile: str,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    if profile not in ("teacher", "student"):
        raise ExportError(f"unknown profile {profile!r}")

    version = (
        await session.execute(
            text(
                """
                SELECT id, document_content, content_hash, document_schema_version
                FROM material_versions WHERE id = :id
                """
            ),
            {"id": material_version_id},
        )
    ).first()
    if version is None:
        raise ExportError("material version not found")

    data = render_docx(version.document_content, profile)
    file_hash = hashlib.sha256(data).hexdigest()

    root = Path(base_dir or EXPORT_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    export_id = uuid.uuid4()
    filename = f"{export_id}.docx"
    (root / filename).write_bytes(data)

    options = {"profile": profile, "format": "docx", "renderer": "chilon-docx-1"}
    await session.execute(
        text(
            """
            INSERT INTO material_exports
                (id, owner_id, material_version_id, profile, format, renderer_version,
                 options_hash, source_document_hash, status, storage_key, file_hash,
                 file_size_bytes, idempotency_key, created_by, finished_at)
            VALUES
                (:id, :owner, :version, :profile, 'docx', 'chilon-docx-1',
                 :options_hash, :source_hash, 'ready', :key, :file_hash,
                 :size, :idem, :owner, now())
            """
        ),
        {
            "id": export_id,
            "owner": owner_id,
            "version": material_version_id,
            "profile": profile,
            "options_hash": hashlib.sha256(
                str(sorted(options.items())).encode("utf-8")
            ).hexdigest(),
            "source_hash": version.content_hash,
            "key": f"exports/{filename}",
            "file_hash": file_hash,
            "size": len(data),
            "idem": f"export:{export_id}",
        },
    )
    await dispatcher.enqueue(
        session,
        aggregate_type="export",
        aggregate_id=str(export_id),
        event_type="export.ready",
        payload={
            "export_id": str(export_id),
            "profile": profile,
            "file_hash": file_hash,
            "material_version_id": str(material_version_id),
        },
    )
    return {
        "export_id": str(export_id),
        "profile": profile,
        "status": "ready",
        "storage_key": f"exports/{filename}",
        "file_hash": file_hash,
        "file_size_bytes": len(data),
        "path": str(root / filename),
        "bytes": data,
    }
