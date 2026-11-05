"""Can the OCR seam read a textbook page? Two pages, one call each."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr, ocr as ocr_service  # noqa: E402

TARGETS = [
    ("必修第一册", 20),
    ("必修第一册", 30),
]


def main() -> int:
    settings = config.load()
    provider = ocr_service.AliyunPaperCutProvider(
        settings.ocr_aliyun_key_id,
        settings.ocr_aliyun_key_secret,
        image_type="scan",
        subject="Math",
    )
    params = {
        "CutType": "question",
        "ImageType": "scan",
        "Subject": "Math",
        "OutputOricoord": "false",
    }
    for name, page_no in TARGETS:
        path = next(Path("D:/Chilon/corpus/textbooks").glob(f"*{name}.pdf"))
        pages = ocr_service.render_pages(path.read_bytes())
        if page_no - 1 >= len(pages):
            print(f"{name}: page {page_no} out of range")
            continue
        payload = provider._call(pages[page_no - 1], params, page_no)
        data = aliyun_ocr.decode_data(payload)
        subjects = []
        for page in (data.get("page_list") or []):
            for subject in (page.get("subject_list") or []):
                text = (subject.get("text") or "").strip()
                if text:
                    subjects.append(text)
        print(f"\n=== {name} page {page_no}: {len(subjects)} block(s)")
        for text in subjects[:4]:
            print("   -", text[:180].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
