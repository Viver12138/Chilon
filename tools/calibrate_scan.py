"""Calibrate the scanner against the 解析版 (answers) paper.

The 解析版 is the harder document: questions and 解析 are interleaved, questions 2 and 8
span pages, and it is 23 pages instead of 4. If the cutter is going to fail anywhere, it
fails here first.

Raw responses are cached in `var/` so re-running the calibration costs nothing — the
vendor bills per call, and a calibration loop that re-bills is a calibration loop nobody
runs twice.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import settings as config  # noqa: E402
from app.services import aliyun_ocr  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402

PAPER = ROOT / "docs/2024年新课标全国Ⅰ卷数学真题（解析版）.pdf"
CACHE = ROOT / "var/aliyun_jiexi.json"
GROUND_TRUTH = ROOT / "docs/2024新课标全国Ⅰ卷数学_OCR切分样例.md"


def fetch() -> list[dict]:
    """Call the vendor once per page, caching the raw responses."""
    if CACHE.exists():
        print(f"using cached responses: {CACHE.name}")
        return json.loads(CACHE.read_text(encoding="utf-8"))

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
    pages = ocr_service.render_pages(PAPER.read_bytes())
    print(f"pages: {len(pages)}")
    captured = []
    for index, png in enumerate(pages, 1):
        payload = provider._call(png, params, index)
        captured.append({"page": index, "response": payload})
        print(f"  page {index}: {len(png)//1024}KB -> ok")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(captured, ensure_ascii=False), encoding="utf-8")
    return captured


def ground_truth() -> dict[int, dict]:
    """Parse the human-curated markdown into per-question facts."""
    text = GROUND_TRUTH.read_text(encoding="utf-8")
    blocks = re.split(r"^### 第 (\d+) 题$", text, flags=re.M)
    facts: dict[int, dict] = {}
    for i in range(1, len(blocks), 2):
        number = int(blocks[i])
        body = blocks[i + 1]
        kind = re.search(r"\*\*题型：\*\*\s*(\S+)", body)
        page = re.search(r"\*\*源 PDF 页码：\*\*\s*([0-9–\-]+)", body)
        knowledge = re.search(r"\*\*知识内容：\*\*\s*(.+)", body)
        answer = re.search(r"\*\*答案[^*]*：\*\*\s*(\S+)", body)
        facts[number] = {
            "type": kind.group(1) if kind else None,
            "page": page.group(1) if page else None,
            "knowledge": knowledge.group(1).strip() if knowledge else None,
            "answer": answer.group(1) if answer else None,
        }
    return facts


def main() -> int:
    truth = ground_truth()
    print(f"ground truth questions: {len(truth)} (expected 19)")

    raw = fetch()
    all_questions = []
    per_page = []
    for entry in raw:
        data = aliyun_ocr.decode_data(entry["response"])
        found = aliyun_ocr.extract_questions(data, page=entry["page"])
        per_page.append((entry["page"], len(found)))
        all_questions.extend(found)

    print("\nsubjects per page:")
    for page, count in per_page:
        print(f"  page {page:2d}: {count}")

    merged = ocr_service.merge_fragments(all_questions)
    numbers = [ocr_service.leading_number(q.stem) or ocr_service.bare_number(q.stem) for q in merged]
    present = [n for n in numbers if n]
    print(f"\nraw subjects : {len(all_questions)}")
    print(f"after merge  : {len(merged)}")
    print(f"numbers found: {sorted(set(present))}")
    print(f"gaps         : {ocr_service.missing_numbers(merged)}")

    print("\nseparation of question text from analysis:")
    polluted = [q for q in merged if re.search(r"【解析】|【详解】|【分析】", q.stem)]
    print(f"  stems still containing 解析: {len(polluted)} (must be 0)")
    with_analysis = [q for q in merged if getattr(q, "analysis", "")]
    print(f"  questions with analysis attached: {len(with_analysis)}")
    with_answer = [q for q in merged if q.answer]
    print(f"  answers salvaged from analysis: {len(with_answer)}")
    for q in with_answer[:5]:
        print(f"    Q{q.number or '?'}: {q.answer[:60]}")

    print("\nper question:")
    for number in sorted(truth):
        match = next(
            (
                q
                for q in merged
                if (ocr_service.leading_number(q.stem) or ocr_service.bare_number(q.stem)) == number
            ),
            None,
        )
        status = "MISS" if match is None else f"{len(match.stem):4d} chars"
        has_answer = "answer" if match and re.search(r"【答案】|答案：", match.stem) else "-"
        print(
            f"  Q{number:2d} {truth[number]['type'] or '?':10s} {status:14s} "
            f"page={truth[number]['page'] or '?':5s} {has_answer}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
