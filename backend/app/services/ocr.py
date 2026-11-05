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

from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

from app import settings as config
from app.services import aliyun_ocr


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
    # a structured provider segments the paper itself; when it does, our own regex
    # segmentation would only throw that structure away
    questions: list = field(default_factory=list)

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



class AliyunPaperCutProvider:
    """Aliyun education OCR (`RecognizeEduPaperCut`).

    Three facts from the vendor's docs shape this code:

    * **PDF is not accepted** — only images, so pages are rasterised first;
    * `CutType` separates the question pass from the answer pass (`question` / `answer`);
    * the response puts a **JSON string** in `Data`, whose inner shape this code could
      not verify from the docs.

    The third point is why `extract_questions` is shape-adaptive and raises
    `ShapeUnknown` instead of returning nothing. **This provider has never been run
    against the real endpoint** — no credentials exist in this environment.
    """

    name = "aliyun"

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        image_type: str = "scan",
        subject: str = "Math",
        action: str = aliyun_ocr.ACTION_CUT,
    ) -> None:
        if not key_id or not key_secret:
            raise OcrUnavailable(
                "the aliyun provider needs CHILON_OCR_ALIYUN_KEY_ID and "
                "CHILON_OCR_ALIYUN_KEY_SECRET"
            )
        self.key_id = key_id
        self.key_secret = key_secret
        self.image_type = image_type if image_type in ("scan", "photo") else "scan"
        if action not in aliyun_ocr.EDUCATION_ACTIONS:
            raise OcrUnavailable(
                f"unknown aliyun action {action!r}; expected one of "
                f"{sorted(aliyun_ocr.EDUCATION_ACTIONS)}"
            )
        self.subject = subject
        self.action = action
        self.version = f"aliyun:{action}"

    def read(self, pdf_bytes: bytes) -> OcrResult:
        import httpx

        questions: list = []
        confidence_pages: list[PageText] = []
        for page_number, png in enumerate(render_pages(pdf_bytes), 1):
            params = {
                "CutType": "question",
                "ImageType": self.image_type,
                "Subject": self.subject,
                "OutputOricoord": "false",
            }
            payload = self._call(png, params, page_number, action=self.action)

            if self.action == aliyun_ocr.ACTION_PAGE:
                # full-page recognition does not segment; it is the fallback for pages a
                # paper-cut call cannot split (textbook pages, answer sheets)
                try:
                    page_text = aliyun_ocr.extract_page_text(payload)
                except aliyun_ocr.ShapeUnknown as exc:
                    raise OcrFailed(f"page {page_number}: {exc}") from exc
                confidence_pages.append(
                    PageText(page_number=page_number, text=page_text, confidence=0.9)
                )
                continue

            data = aliyun_ocr.decode_data(payload)
            try:
                found = aliyun_ocr.extract_questions(data, page=page_number)
            except aliyun_ocr.ShapeUnknown as exc:
                raise OcrFailed(
                    f"page {page_number}: {exc}. The vendor response shape is not what "
                    "this reader expects; adjust aliyun_ocr.extract_questions."
                ) from exc
            questions.extend(found)
            # the vendor does not return a confidence; treat "it parsed" as usable and
            # let the review gate catch bad scans through other signals
            confidence_pages.append(
                PageText(page_number=page_number, text="\n".join(q.as_text() for q in found), confidence=0.9)
            )
        return OcrResult(
            pages=confidence_pages,
            engine=self.name,
            version=self.version,
            questions=questions,
        )

    def _call(
        self, png: bytes, params: dict[str, str], page_number: int, *, action: str | None = None
    ) -> dict:
        import httpx

        headers = aliyun_ocr.sign_request(
            access_key_id=self.key_id,
            access_key_secret=self.key_secret,
            action=action or self.action,
            params=params,
            body=png,
            timestamp=aliyun_ocr.now_timestamp(),
        )
        url = f"https://{aliyun_ocr.OCR_HOST}/?{aliyun_ocr.canonical_query(params)}"
        response = httpx.post(
            url, headers=headers, content=png, timeout=60, follow_redirects=True
        )
        if response.status_code != 200:
            raise OcrFailed(
                f"aliyun OCR returned {response.status_code} on page {page_number}: "
                f"{response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise OcrFailed(f"aliyun OCR returned non-JSON: {response.text[:200]}") from exc


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
    if provider == "aliyun":
        return AliyunPaperCutProvider(
            settings.ocr_aliyun_key_id,
            settings.ocr_aliyun_key_secret,
            image_type=settings.ocr_aliyun_image_type,
            subject=settings.ocr_aliyun_subject,
            action=settings.ocr_aliyun_action,
        )
    raise OcrUnavailable(
        f"unknown OCR provider {provider!r}; expected none|fake|tesseract|cloud|aliyun"
    )
