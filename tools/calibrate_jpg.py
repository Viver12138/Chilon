"""Calibrate the JPG pages of 全国2卷, and compare scan vs photo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402

FOLDER = ROOT / "docs/全国2卷数学-jpg"
CACHE = ROOT / "var/aliyun_g2_jpg.json"


def provider():
    s = config.load()
    return ocr_service.AliyunPaperCutProvider(
        s.ocr_aliyun_key_id,
        s.ocr_aliyun_key_secret,
        image_type=s.ocr_aliyun_image_type,
        subject=s.ocr_aliyun_subject,
    )


def call_page(p, image: Path, image_type: str, page: int) -> dict:
    params = {
        "CutType": "question",
        "ImageType": image_type,
        "Subject": "Math",
        "OutputOricoord": "false",
    }
    return p._call(image.read_bytes(), params, page)


def main() -> int:
    pages = sorted(FOLDER.glob("*.jpg"))
    print(f"pages: {len(pages)}")

    if CACHE.exists():
        print("using cache")
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        p = provider()
        raw = []
        for index, image in enumerate(pages, 1):
            payload = call_page(p, image, "scan", index)
            raw.append({"page": index, "response": payload})
            print(f"  page {index}: ok")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    total = 0
    numbers: list[int] = []
    for entry in raw:
        data = aliyun_ocr.decode_data(entry["response"])
        found = aliyun_ocr.extract_questions(data, page=entry["page"])
        ids = [(q.number, ocr_service.leading_number(q.stem) or ocr_service.bare_number(q.stem)) for q in found]
        print(f"  page {entry['page']}: {len(found)} subject(s) ids={[i[0] for i in ids]} leads={[i[1] for i in ids]}")
        total += len(found)
        numbers.extend(n for _, n in ids if n)

    merged = ocr_service.merge_fragments(
        [
            q
            for entry in raw
            for q in aliyun_ocr.extract_questions(
                aliyun_ocr.decode_data(entry["response"]), page=entry["page"]
            )
        ]
    )
    leading = sorted({n for n in (ocr_service.leading_number(q.stem) or ocr_service.bare_number(q.stem) for q in merged) if n})
    print(f"\nraw subjects : {total}")
    print(f"after merge  : {len(merged)}")
    print(f"numbers      : {leading}")
    print(f"gaps         : {[n for n in range(1, (leading[-1] if leading else 0) + 1) if n not in leading]}")

    print("\n-- scan vs photo on page 1 --")
    p = provider()
    for image_type in ("scan", "photo"):
        payload = call_page(p, pages[0], image_type, 1)
        data = aliyun_ocr.decode_data(payload)
        found = aliyun_ocr.extract_questions(data, page=1)
        print(f"  {image_type:5}: {len(found)} subject(s), ids={[q.number for q in found]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
