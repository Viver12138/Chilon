"""Aliyun paper-cut smoke test: run it once with real credentials.

Purpose: turn "the provider is written but unverified" into "verified, and the reader
is adjusted from evidence". It makes **one real HTTP call per page** and prints what
came back, so the response reader can be corrected in one sitting instead of by trial.

    export CHILON_OCR_ALIYUN_KEY_ID=...
    export CHILON_OCR_ALIYUN_KEY_SECRET=...
    python tools/aliyun_ocr_smoke.py 试卷.pdf --dump /tmp/aliyun_papercut.json

It deliberately does not touch the database: this is a probe of the vendor, not of
ingestion. Once the structure is known, run the upload path.

Exit codes: 0 printed a readable payload; 1 the call or the reader failed; 2 missing
credentials or input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402


def load_pages(path: Path, *, page: int | None) -> list[bytes]:
    """Return PNG bytes per page. Images pass through; PDFs are rasterised."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = ocr_service.render_pages(path.read_bytes())
        if page is not None:
            if not 1 <= page <= len(pages):
                raise SystemExit(f"page {page} is outside 1..{len(pages)}")
            return [pages[page - 1]]
        return pages
    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"):
        return [path.read_bytes()]
    raise SystemExit(f"unsupported input type {suffix!r}; pass a PDF or an image")


def report(payload: dict, page_number: int) -> int:
    print(f"\n=== page {page_number} ===")
    print("top-level keys:", sorted(payload.keys()))

    data = aliyun_ocr.decode_data(payload)
    print("\n-- Data, as this reader sees it --")
    print(aliyun_ocr.describe_shape(data, max_depth=3))

    try:
        questions = aliyun_ocr.extract_questions(data, page=page_number)
    except aliyun_ocr.ShapeUnknown as exc:
        print(f"\n!! reader could not find questions: {exc}")
        print("\nNext step: look at the structure above, then teach")
        print("      app/services/aliyun_ocr.py::TEXT_KEYS / OPTION_KEYS / walk()")
        return 1

    print(f"\n-- questions found: {len(questions)} --")
    for index, question in enumerate(questions[:3], 1):
        print(f"  Q{index}: {question.stem[:80]}")
        if question.options:
            print(f"       options: {question.options[:4]}")
        if question.answer:
            print(f"       answer : {question.answer[:60]}")
    if len(questions) > 3:
        print(f"  … {len(questions) - 3} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Aliyun paper-cut OCR once")
    parser.add_argument("file", help="PDF or image to send")
    parser.add_argument("--page", type=int, default=1, help="1-based page for PDFs")
    parser.add_argument("--all-pages", action="store_true", help="send every PDF page")
    _defaults = config.load()
    parser.add_argument(
        "--subject",
        default=os.environ.get("CHILON_OCR_ALIYUN_SUBJECT") or _defaults.ocr_aliyun_subject or "Math",
    )
    parser.add_argument(
        "--image-type",
        default=os.environ.get("CHILON_OCR_ALIYUN_IMAGE_TYPE")
        or config.load().ocr_aliyun_image_type
        or "scan",
        choices=("scan", "photo"),
    )
    parser.add_argument("--dump", default=None, help="write the raw JSON response here")
    args = parser.parse_args()

    # same source as the application: environment first, then .env. A probe that reads
    # credentials differently from the app can pass while the app cannot start.
    loaded = config.load()
    key_id = os.environ.get("CHILON_OCR_ALIYUN_KEY_ID") or loaded.ocr_aliyun_key_id
    key_secret = os.environ.get("CHILON_OCR_ALIYUN_KEY_SECRET") or loaded.ocr_aliyun_key_secret
    if not key_id or not key_secret:
        print(
            "missing credentials: set CHILON_OCR_ALIYUN_KEY_ID and "
            "CHILON_OCR_ALIYUN_KEY_SECRET (environment or .env)",
            file=sys.stderr,
        )
        return 2
    if not os.environ.get("CHILON_OCR_ALIYUN_KEY_ID"):
        print("credentials: read from .env")

    path = Path(args.file)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    pages = load_pages(path, page=None if args.all_pages else args.page)
    print(f"file: {path.name}  pages: {len(pages)}  subject: {args.subject}  type: {args.image_type}")

    provider = ocr_service.AliyunPaperCutProvider(
        key_id, key_secret, image_type=args.image_type, subject=args.subject
    )
    params = {
        "CutType": "question",
        "ImageType": args.image_type,
        "Subject": args.subject,
        "OutputOricoord": "false",
    }

    raw_responses = []
    failures = 0
    for index, png in enumerate(pages, 1):
        print(f"\n-- calling RecognizeEduPaperCut (page {index}, {len(png)} bytes) --")
        try:
            payload = provider._call(png, params, index)
        except ocr_service.OcrFailed as exc:
            print(f"!! {exc}", file=sys.stderr)
            failures += 1
            continue
        raw_responses.append({"page": index, "response": payload})
        failures += report(payload, index)

    if args.dump:
        target = Path(args.dump)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(raw_responses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nraw response written to {target}")

    if failures:
        print(f"\n{failures} page(s) needed attention (see above).")
        return 1
    print("\nAll pages parsed. Adjust TEXT_KEYS only if fields were silently skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
