"""PDF export by converting the already-projected DOCX.

Why conversion instead of a PDF writer: CJK text needs an embedded font subset, and
a hand-rolled writer would either drop Chinese or ship a font we do not have the
right to embed. LibreOffice is already installed on the machine and does the font
work correctly.

**The guarantee is inherited, not re-established.** The answer-absence property is
established at the DOCX layer (one AST, student projection, verified by unzipping
and searching). PDF is a conversion of that file, so it cannot reintroduce an answer
that is not in the source. This module therefore tests what it can prove: a valid
PDF, and teacher/student PDFs that differ.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class PdfRendererUnavailable(Exception):
    """No LibreOffice binary was found."""


CANDIDATE_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def find_soffice() -> Path | None:
    """Locate LibreOffice: explicit env var, then PATH, then the usual install paths."""
    explicit = os.environ.get("CHILON_SOFFICE")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return Path(found)
    for candidate in CANDIDATE_PATHS:
        if Path(candidate).exists():
            return Path(candidate)
    return None


def convert_docx_to_pdf(docx_bytes: bytes, *, timeout_seconds: int = 45) -> bytes:
    """Convert DOCX bytes to PDF bytes. Raises PdfRendererUnavailable if no binary."""
    binary = find_soffice()
    if binary is None:
        raise PdfRendererUnavailable(
            "LibreOffice not found; set CHILON_SOFFICE or install LibreOffice "
            "(PDF export is unavailable, DOCX export still works)"
        )

    with tempfile.TemporaryDirectory(prefix="chilon-pdf-") as workdir:
        source = Path(workdir) / "document.docx"
        source.write_bytes(docx_bytes)
        # LibreOffice needs a writable user profile. Without an explicit one it uses
        # the real user profile, which fails (or crashes) when another instance holds
        # it — the observed failure was exit 0xC0000409 with no output at all.
        profile = Path(workdir) / "lo-profile"
        profile.mkdir(exist_ok=True)
        command = [
            str(binary),
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--norestore",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            workdir,
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # a hanging converter is worse than a missing one: it burns the request
            raise PdfRendererUnavailable(
                f"PDF conversion did not finish within {timeout_seconds}s; "
                "LibreOffice may need resources this environment cannot provide"
            ) from exc

        produced = Path(workdir) / "document.pdf"
        if not produced.exists():
            detail = (completed.stderr or b"").decode("utf-8", "replace")[:400]
            raise PdfRendererUnavailable(
                f"PDF conversion produced no file (exit {completed.returncode}): {detail}"
            )
        data = produced.read_bytes()
        if not data.startswith(b"%PDF"):
            raise PdfRendererUnavailable("converter produced a file that is not a PDF")
        return data


def pdf_text_is_probeable() -> bool:
    """True when a test can read the PDF back.

    Kept as a function so the test states the dependency instead of assuming it: if
    no extractor is available we assert structure only, and say so.
    """
    return shutil.which("pdftotext") is not None


def extract_pdf_text(pdf_bytes: bytes) -> str | None:
    """Best-effort text extraction; returns None when no extractor exists."""
    if not pdf_text_is_probeable():
        return None
    with tempfile.TemporaryDirectory(prefix="chilon-pdftext-") as workdir:
        path = Path(workdir) / "document.pdf"
        path.write_bytes(pdf_bytes)
        completed = subprocess.run(
            ["pdftotext", str(path), "-"], capture_output=True, timeout=60, check=False
        )
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", "replace")


_ = sys
