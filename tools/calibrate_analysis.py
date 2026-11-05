"""Compare 原卷版 vs 解析版 to pick an evidence-based discriminator.

Two candidate signals:
  * share of subjects that carry no question number (解析 prose arrives unnumbered);
  * share of subjects whose text contains an analysis marker.

The threshold is chosen from these two documents, and both are cached so the comparison
is reproducible without paying for it again.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402

MARKERS = re.compile(r"【解析】|【详解】|【分析】|【答案】|故答案为|答案为")


def fetch(pdf: Path, cache: Path) -> list[dict]:
    if cache.exists():
        print(f"  using cache {cache.name}")
        return json.loads(cache.read_text(encoding="utf-8"))
    settings = config.load()
    provider = ocr_service.AliyunPaperCutProvider(
        settings.ocr_aliyun_key_id,
        settings.ocr_aliyun_key_secret,
        image_type=settings.ocr_aliyun_image_type,
        subject=settings.ocr_aliyun_subject,
    )
    params = {
        "CutType": "question",
        "ImageType": settings.ocr_aliyun_image_type,
        "Subject": settings.ocr_aliyun_subject,
        "OutputOricoord": "false",
    }
    pages = ocr_service.render_pages(pdf.read_bytes())
    captured = []
    for index, png in enumerate(pages, 1):
        captured.append({"page": index, "response": provider._call(png, params, index)})
        print(f"  page {index}/{len(pages)}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(captured, ensure_ascii=False), encoding="utf-8")
    return captured


def analyse(label: str, raw: list[dict]) -> dict:
    subjects = []
    for entry in raw:
        data = aliyun_ocr.decode_data(entry["response"])
        for page in data.get("page_list") or []:
            for subject in page.get("subject_list") or []:
                text = (subject.get("text") or "").strip()
                if text:
                    subjects.append(text)

    total = len(subjects) or 1
    numbered = sum(
        1
        for text in subjects
        if ocr_service.leading_number(text) or ocr_service.leading_number(text) is None
        and _bare_continues(text)
    )
    # a subject is "numbered" when it starts with a question number in any form
    numbered = sum(
        1
        for text in subjects
        if ocr_service.leading_number(text) is not None
    )
    marked = sum(1 for text in subjects if MARKERS.search(text))
    stats = {
        "label": label,
        "subjects": len(subjects),
        "numbered": numbered,
        "unnumbered_share": round((len(subjects) - numbered) / total, 3),
        "marker_share": round(marked / total, 3),
    }
    print(f"\n{label}")
    for key, value in stats.items():
        if key != "label":
            print(f"  {key:16} {value}")
    return stats


def _bare_continues(text: str) -> bool:
    return ocr_service.bare_number(text) is not None


def main() -> int:
    pairs = [
        ("原卷版", ROOT / "docs/2024年新课标全国Ⅰ卷数学真题（原卷版）.pdf", ROOT / "var/aliyun_yuanjuan.json"),
        ("解析版", ROOT / "docs/2024年新课标全国Ⅰ卷数学真题（解析版）.pdf", ROOT / "var/aliyun_jiexi.json"),
    ]
    results = []
    for label, pdf, cache in pairs:
        print(f"\n== {label}")
        results.append(analyse(label, fetch(pdf, cache)))

    print("\n-- discriminator --")
    for stats in results:
        print(
            f"  {stats['label']}: unnumbered={stats['unnumbered_share']:.0%} "
            f"markers={stats['marker_share']:.0%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
