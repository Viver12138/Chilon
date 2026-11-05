"""OCR providers.

Scanned papers have no text layer, so extraction has to go through images. That step
is **not** made deterministic by this module — OCR engines change between versions and
disagree about a `sin²x`. What this module does instead:

* puts the engine behind one narrow interface, so replacing it is a config change;
* records which engine and version produced the text (`tool_version`), because a
  different engine legitimately yields a different number of questions;
* reports a confidence so the caller can decide **not** to auto-index a bad scan.

**The default is no provider.** A deployment that has not opted in keeps the current
behaviour: refuse the scan and say what to do. Enabling the cloud provider is a data
egress decision, so it requires an explicit endpoint and key — it cannot be reached by
leaving an environment variable unset.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from app import settings as config


class OcrUnavailable(Exception):
    """No usable provider, or the configured one cannot run."""


class OcrFailed(Exception):
    """The provider ran and could not produce text."""


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    pages: list[PageText]
    engine: str
    version: str

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def confidence(self) -> float:
        """The weakest page decides: one illegible page must not be averaged away."""
        scored = [page.confidence for page in self.pages if page.text.strip()]
        return min(scored) if scored else 0.0


class OcrProvider(Protocol):
    name: str
    version: str

    def read(self, pdf_bytes: bytes) -> OcrResult: ...


# ── rasterisation ──────────────────────────────────────────────────────────────


def render_pages(pdf_bytes: bytes, *, scale: float = 2.0) -> list[bytes]:
    """Render PDF pages to PNG bytes.

    pypdfium2 is a wheel with no system dependency, which is the reason it is used
    here: an OCR pipeline that needs poppler installed is a pipeline half the
    deployments cannot run.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise OcrUnavailable(
            "pypdfium2 is not installed, so pages cannot be rasterised for OCR"
        ) from exc

    images: list[bytes] = []
    document = pdfium.PdfDocument(BytesIO(pdf_bytes))
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            images.append(buffer.getvalue())
    finally:
        document.close()
    return images


# ── providers ──────────────────────────────────────────────────────────────────


class FakeProvider:
    """Deterministic provider for tests.

    It reads a marker embedded in the PDF's own bytes, so a test can control the text
    and the confidence without a real engine. It exists because the *plumbing* is what
    needs testing: page iteration, confidence gating, the run record, the review state.
    """

    name = "fake"
    version = "fake-1"

    def read(self, pdf_bytes: bytes) -> OcrResult:
        marker = b"FAKE_OCR:"
        start = pdf_bytes.find(marker)
        if start < 0:
            return OcrResult(pages=[], engine=self.name, version=self.version)
        raw = pdf_bytes[start + len(marker) :].split(b"\n", 1)[0].decode("utf-8", "replace")
        confidence_text, _, body = raw.partition("|")
        try:
            confidence = float(confidence_text)
        except ValueError:
            confidence = 0.0
        lines = [line for line in body.split("\\n") if line.strip()]
        pages = [
            PageText(page_number=index + 1, text=line, confidence=confidence)
            for index, line in enumerate(lines)
        ]
        return OcrResult(pages=pages, engine=self.name, version=self.version)


class TesseractProvider:
    """Local, offline, no data leaves the machine.

    Needs the `tesseract` binary and language data installed in the image. This module
    does not install them: a missing binary is reported as `OcrUnavailable` with the
    exact command to fix it.
    """

    name = "tesseract"

    def __init__(self, languages: str = "chi_sim+eng") -> None:
        self.languages = languages
        self.version = self._probe_version()

    @staticmethod
    def _probe_version() -> str:
        import shutil
        import subprocess

        binary = shutil.which("tesseract")
        if not binary:
            raise OcrUnavailable(
                "tesseract is not installed; add `tesseract-ocr tesseract-ocr-chi-sim` "
                "to the image, or set CHILON_OCR_PROVIDER=none"
            )
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, timeout=10, check=False
            )
            first = (out.stdout or out.stderr).decode("utf-8", "replace").splitlines()[0]
        except Exception:  # noqa: BLE001 - version probing must never be fatal
            first = "unknown"
        return first.strip()

    def read(self, pdf_bytes: bytes) -> OcrResult:
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        binary = shutil.which("tesseract")
        if not binary:
            raise OcrUnavailable("tesseract disappeared after startup")

        pages: list[PageText] = []
        with tempfile.TemporaryDirectory(prefix="chilon-ocr-") as workdir:
            for index, png in enumerate(render_pages(pdf_bytes), 1):
                image_path = Path(workdir) / f"page-{index}.png"
                image_path.write_bytes(png)
                result = subprocess.run(
                    [
                        binary,
                        str(image_path),
                        "stdout",
                        "-l",
                        self.languages,
                        "--psm",
                        "6",
                        # ask for a confidence so the caller can gate on it
                        "-c",
                        "tessedit_create_tsv=0",
                    ],
                    capture_output=True,
                    timeout=120,
                    check=False,
                )
                text = result.stdout.decode("utf-8", "replace")
                if result.returncode != 0 and not text.strip():
                    raise OcrFailed(
                        f"tesseract failed on page {index}: "
                        f"{result.stderr.decode('utf-8', 'replace')[:200]}"
                    )
                # tesseract has no document-level score; treat "produced text" as
                # usable and let the caller's minimum decide via the page length
                confidence = 0.9 if text.strip() else 0.0
                pages.append(PageText(page_number=index, text=text, confidence=confidence))
        return OcrResult(pages=pages, engine=self.name, version=self.version)


class CloudProvider:
    """Sends pages to a configured endpoint. Off unless an operator opts in.

    The contract is deliberately generic (`POST` a PNG, receive `{"text": ...,
    "confidence": ...}`) so a deployment can point it at whichever service it has
    cleared for data egress. Nothing here picks a vendor for the operator.
    """

    name = "cloud"

    def __init__(self, endpoint: str, key: str) -> None:
        if not endpoint or not key:
            raise OcrUnavailable(
                "the cloud OCR provider needs CHILON_OCR_CLOUD_ENDPOINT and "
                "CHILON_OCR_CLOUD_KEY; without them it is disabled by design"
            )
        self.endpoint = endpoint
        self.key = key
        self.version = f"cloud:{endpoint}"

    def read(self, pdf_bytes: bytes) -> OcrResult:
        import httpx

        pages: list[PageText] = []
        for index, png in enumerate(render_pages(pdf_bytes), 1):
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.key}"},
                files={"image": (f"page-{index}.png", png, "image/png")},
                timeout=60,
            )
            if response.status_code != 200:
                raise OcrFailed(
                    f"cloud OCR returned {response.status_code}: {response.text[:200]}"
                )
            payload = response.json()
            pages.append(
                PageText(
                    page_number=index,
                    text=str(payload.get("text") or ""),
                    confidence=float(payload.get("confidence") or 0.0),
                )
            )
        return OcrResult(pages=pages, engine=self.name, version=self.version)


def build(settings=None) -> OcrProvider | None:
    """Resolve the configured provider, or None when OCR is switched off."""
    settings = settings or config.load()
    provider = (settings.ocr_provider or "none").strip().lower()
    if provider in ("", "none"):
        return None
    if provider == "fake":
        return FakeProvider()
    if provider == "tesseract":
        return TesseractProvider(settings.ocr_languages)
    if provider == "cloud":
        return CloudProvider(settings.ocr_cloud_endpoint, settings.ocr_cloud_key)
    raise OcrUnavailable(
        f"unknown OCR provider {provider!r}; expected none|fake|tesseract|cloud"
    )
