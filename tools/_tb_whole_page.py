"""Call the whole-page OCR action directly and see whether prose survives."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr, ocr as ocr_service  # noqa: E402


def call(action: str, image: bytes, extra: dict[str, str]) -> dict:
    settings = config.load()
    headers = aliyun_ocr.sign_request(
        access_key_id=settings.ocr_aliyun_key_id,
        access_key_secret=settings.ocr_aliyun_key_secret,
        action=action,
        params=extra,
        body=image,
        timestamp=aliyun_ocr.now_timestamp(),
    )
    url = f"https://{aliyun_ocr.OCR_HOST}/?{aliyun_ocr.canonical_query(extra)}"
    response = httpx.post(url, headers=headers, content=image, timeout=90, follow_redirects=True)
    print(f"{action}: HTTP {response.status_code}")
    if response.status_code != 200:
        print(response.text[:400])
        return {}
    return response.json()


def main() -> int:
    path = next(Path("D:/Chilon/corpus/textbooks").glob("*必修第一册.pdf"))
    pages = ocr_service.render_pages(path.read_bytes())
    image = pages[19]

    for action in ("RecognizeEduPaperOcr",):
        payload = call(action, image, {"ImageType": "scan", "Subject": "Math"})
        if not payload:
            continue
        print("top keys:", list(payload.keys()))
        data = aliyun_ocr.decode_data(payload)
        print("data keys:", list(data.keys())[:10])
        blob = json.dumps(data, ensure_ascii=False)
        print("data chars:", len(blob))
        print(blob[:900])
    return 0


if __name__ == "__main__":
    sys.exit(main())
