"""Verify the analysis_version reason against the cached 解析版 responses.

No vendor call: the 23 pages were captured earlier and are on disk. This is the last
unverified claim in D.72.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/Chilon")
sys.path.insert(0, str(ROOT / "backend"))

from app.services import aliyun_ocr, ingestion  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402

CACHE = ROOT / "var/aliyun_jiexi.json"
if not CACHE.exists():
    print("cache missing:", CACHE)
    raise SystemExit(2)

raw = json.loads(CACHE.read_text(encoding="utf-8"))
questions = []
for entry in raw:
    data = aliyun_ocr.decode_data(entry["response"])
    questions.extend(aliyun_ocr.extract_questions(data, page=entry["page"]))

merged = ocr_service.merge_fragments(questions)
gaps = ocr_service.missing_numbers(merged)
analysis_blocks = sum(1 for q in merged if getattr(q, "analysis", ""))
numbered = sum(
    1
    for q in merged
    if ocr_service.leading_number(q.stem) or ocr_service.bare_number(q.stem)
)

print(f"raw subjects     : {len(questions)}")
print(f"after merge      : {len(merged)}")
print(f"with a number    : {numbered}")
print(f"analysis blocks  : {analysis_blocks}")
print(f"gaps             : {gaps}")

reasons = ingestion.review_reasons(
    gaps=gaps,
    confidence=0.9,
    min_confidence=0.6,
    analysis_blocks=analysis_blocks,
    questions=numbered,
)
print(f"\nreview reasons   : {reasons}")

expected_analysis = analysis_blocks >= max(2, numbered // 2)
print(f"analysis rule    : blocks={analysis_blocks} vs half of questions={numbered // 2}")
print(f"would flag 解析版 : {expected_analysis}")
print(f"flagged           : {ingestion.REVIEW_ANALYSIS_VERSION in reasons}")
