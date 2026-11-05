"""Tests for the smoke tool's offline parts.

The smoke tool itself needs credentials, so what is tested here is everything it does
*before* the network: decoding `Data`, summarising an unknown shape so an operator can
read it, and refusing bad input with a clear message. If these are wrong, the one run
an operator gets against the real endpoint is wasted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import aliyun_ocr  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


def main() -> int:
    print("1. Data is a JSON string and must be decoded first")
    payload = {"RequestId": "x", "Data": json.dumps({"QuestionInfoList": [{"Text": "题"}]})}
    decoded = aliyun_ocr.decode_data(payload)
    check(isinstance(decoded, dict), f"decoded to an object (got {type(decoded).__name__})")
    check("QuestionInfoList" in decoded, "the inner key survives decoding")
    check(
        aliyun_ocr.decode_data({"Data": {"already": 1}}) == {"already": 1},
        "an object payload passes through unchanged",
    )
    check(
        aliyun_ocr.decode_data({"Data": "not json"}) == "not json",
        "a non-JSON string is returned as-is rather than crashing",
    )

    print("2. an unknown shape is described, not swallowed")
    shape = aliyun_ocr.describe_shape(decoded)
    check("QuestionInfoList" in shape, "the description names the list")
    check("list[1]" in shape, "and its length")
    deep = aliyun_ocr.describe_shape({"a": {"b": {"c": {"d": 1}}}}, max_depth=2)
    check("…" in deep, "depth is bounded so a huge payload stays readable")

    print("3. the description handles scalars and empty lists")
    check(aliyun_ocr.describe_shape([]) == "[]", "an empty list is shown as []")
    check("int" in aliyun_ocr.describe_shape({  "x": 5}), "a scalar names its type")

    print("4. a payload with no questions raises with the keys it saw")
    try:
        aliyun_ocr.extract_questions(json.dumps({"Rows": [{"Value": 1}]}))
        check(False, "an unrecognised payload produced questions")
    except aliyun_ocr.ShapeUnknown as exc:
        check("Rows" in str(exc), f"the actual key is in the message ({str(exc)[:60]})")

    print("5. options and answers are picked up from the structured payload")
    questions = aliyun_ocr.extract_questions(
        json.dumps(
            {
                "QuestionInfoList": [
                    {
                        "Text": "1. 求 f(x)=sin(2x+π/3) 的最小正周期。",
                        "OptionList": ["A. π", "B. 2π", "C. π/2", "D. 4π"],
                    },
                    {"Text": "2. 化简 sin²x+cos²x。", "Answer": "1"},
                ]
            }
        ),
        page=2,
    )
    check(len(questions) == 2, f"two questions (got {len(questions)})")
    check(len(questions[0].options) == 4, "options are kept")
    check(questions[1].answer == "1", "the answer is attached")
    check(questions[0].page == 2, "the page is carried")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: the one real run an operator gets will be readable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
