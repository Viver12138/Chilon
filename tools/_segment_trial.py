"""How well does the text path segment these papers? Try a few and look."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from app.services import ingestion  # noqa: E402

SAMPLES = [
    "2024新高考1(山东,广东,湖南,湖北,河北,江苏,福建,浙江,河南,江西,安徽).pdf",
    "2023北京.pdf",
    "2015全国1(河南,河北,山西,江西).pdf",
    "2012全国(大纲)(贵州,甘肃,青海,西藏,广西).pdf",
]


def main() -> int:
    folder = ROOT / "corpus/gaokao-papers"
    for name in SAMPLES:
        path = folder / name
        if not path.exists():
            print(f"\n== missing: {name}")
            continue
        blocks = ingestion.paragraphs_for("application/pdf", path.read_bytes())
        segments = ingestion.segment(blocks)
        print(f"\n== {name}")
        print(f"   paragraphs={len(blocks)} segments={len(segments)}")
        for item in segments[:3]:
            head = (item.text or "").replace("\n", " ")
            print(f"   [{item.question_no}] {head[:110]}")
        if segments:
            last = segments[-1]
            print(f"   last [{last.question_no}] {(last.text or '')[:110]}")
        numbers = [s.question_no for s in segments if s.question_no]
        print(f"   numbers={numbers[:25]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
