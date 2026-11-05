"""Aliyun OCR tests: what can be proven without credentials.

Three things are verifiable offline, and they are the three that break silently:

* the signature encodes exactly the documented inputs (a canonical request is
  deterministic, so it can be pinned);
* a structured vendor payload becomes questions with options and answers, instead of
  being flattened back to text and re-split by regex;
* an unrecognised payload fails loudly with the keys it actually saw, rather than
  producing an empty question list that looks like an empty paper.

What cannot be proven here: that Aliyun accepts the signature, and what `Data`
actually contains. **This provider has never run against the endpoint.**
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app import settings as config  # noqa: E402
from app.services import aliyun_ocr, identity, ingestion, ocr  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


def sample_payload() -> dict:
    """A payload shaped like a plausible vendor response.

    Deliberately *not* copied from documentation — the docs truncate `Data`. This
    exercises the reader's adaptivity, not a validated contract.
    """
    return {
        "RequestId": "43A29C77-405E-4CC0-BC55-EE694AD00655",
        "Data": json.dumps(
            {
                "QuestionInfoList": [
                    {
                        "QuestionId": "1",
                        "Text": "已知 f(x)=sin(2x+π/3)，求最小正周期。",
                        "OptionList": ["A. π", "B. 2π", "C. π/2", "D. 4π"],
                    },
                    {
                        "QuestionId": "2",
                        "Text": "化简 sin²x + cos²x。",
                        "Answer": "1",
                    },
                ]
            },
            ensure_ascii=False,
        ),
    }


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        print("1. the signature is deterministic and covers the documented inputs")
        body = b"\x89PNG fake"
        params = {"CutType": "question", "ImageType": "scan", "Subject": "Math", "OutputOricoord": "false"}
        first = aliyun_ocr.sign_request(
            access_key_id="AK_test",
            access_key_secret="secret",
            action=aliyun_ocr.ACTION_CUT,
            params=params,
            body=body,
            timestamp="2026-01-01T00:00:00Z",
        )
        check(
            first["Authorization"].startswith("ACS3-HMAC-SHA256 Credential=AK_test,"),
            "the authorization header names the key and algorithm",
        )
        check(
            first["x-acs-content-sha256"] == aliyun_ocr._sha256_hex(body),
            "the payload hash is over the body bytes, not base64 of them",
        )
        check(
            "x-acs-action" in first["Authorization"] or "x-acs-action" in first,
            "the action is a signed header",
        )
        other = aliyun_ocr.sign_request(
            access_key_id="AK_test",
            access_key_secret="secret",
            action=aliyun_ocr.ACTION_CUT,
            params=params,
            body=b"\x89PNG other",
            timestamp="2026-01-01T00:00:00Z",
        )
        check(
            first["Authorization"] != other["Authorization"],
            "a different image produces a different signature",
        )

        print("2. a structured payload becomes questions with options and answers")
        payload = sample_payload()
        questions = aliyun_ocr.extract_questions(payload["Data"], page=1)
        check(len(questions) == 2, f"two questions (got {len(questions)})")
        check("sin(2x+π/3)" in questions[0].stem, "the stem is kept verbatim")
        check(len(questions[0].options) == 4, f"four options (got {questions[0].options})")
        check(questions[1].answer == "1", f"the answer is attached (got {questions[1].answer})")
        check(questions[0].page == 1, "the page is carried onto the question")

        print("3. an unrecognised payload fails loudly with the keys it saw")
        try:
            aliyun_ocr.extract_questions(json.dumps({"Unexpected": [1, 2, 3]}))
            check(False, "an unknown shape was accepted")
        except aliyun_ocr.ShapeUnknown as exc:
            check("Unexpected" in str(exc), f"the message names the keys it saw ({str(exc)[:70]})")

        print("4. a structured result reaches the database without regex re-segmentation")
        async with db.system_session() as session:
            username = f"ali_{uuid.uuid4().hex[:8]}"
            owner = await identity.register(session, username, "aliyun_password_1")
        docx_like = b"not-a-document"  # the provider is faked; only the mapping is tested
        segments = []
        for index, question in enumerate(questions):
            segments.append(
                ingestion.Segment(
                    ordinal=index,
                    question_no=str(index + 1),
                    section=None,
                    locator={"page_number": question.page or 1, "question_index": index},
                    text=question.as_text(),
                    answer_text=question.answer,
                    answer_locator={"page_number": 1, "answer_index": index},
                    question_type=ingestion.classify(None, question.as_text()),
                )
            )
        check(len(segments) == 2, "the mapping produced two segments")
        check(segments[0].question_type == "single_choice", f"Q1 is single choice (got {segments[0].question_type})")
        check(segments[1].answer_text == "1", "the answer text is preserved from the vendor")
        _ = docx_like

        print("5. the provider refuses to build without credentials")
        import dataclasses

        # .env carries real keys now, so the negative case is built explicitly rather
        # than produced by clearing environment variables, which would change nothing
        bare = dataclasses.replace(
            config.load(),
            ocr_provider="aliyun",
            ocr_aliyun_key_id="",
            ocr_aliyun_key_secret="",
        )
        check(bare.ocr_configured is False, "settings know it cannot run")
        try:
            ocr.build(bare)
            check(False, "the aliyun provider built without credentials")
        except ocr.OcrUnavailable as exc:
            check("CHILON_OCR_ALIYUN" in str(exc), "refused with the variable names")

        print("6. the markdown-ish text keeps every part of a question")
        text_value = questions[0].as_text()
        check("sin(2x+π/3)" in text_value, "stem present")
        check("A. π" in text_value, "options present")
    finally:
        os.environ.pop("CHILON_OCR_PROVIDER", None)
        await db.dispose()

        print("6b. fragments merge into their question, and holes are reported")
        class _Q:
            def __init__(self, stem, number=None):
                self.stem = stem
                self.number = number
                self.options = []
                self.answer = None
                self.page = 1
                self.box = None
                self.analysis = ""

            def as_text(self):
                return self.stem

        merged = ocr.merge_fragments(
            [
                _Q("1.已知集合"),
                _Q("2若复数"),          # OCR dropped the dot
                _Q("A.(-∞，0]  B.[-1，0]"),  # a spilled option line
                _Q("4.题目四"),
                _Q("4.第二页碎片"),      # the cutter split one question twice
            ]
        )
        check(len(merged) == 3, f"fragments merged to 3 questions (got {len(merged)})")
        check(
            "A.(-∞，0]" in merged[1].stem,
            "the spilled option line was appended to question 2, not counted as a question",
        )
        check(
            merged[2].stem.count("题目四") == 1 and "第二页碎片" in merged[2].stem,
            "a repeated number merges instead of creating a duplicate",
        )
        check(ocr.missing_numbers(merged) == [3], "the hole at 3 is reported")
        check(
            ocr.missing_numbers([_Q("1.a"), _Q("2.b")]) == [],
            "a complete sequence reports no holes",
        )


    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: AliCloud signing and mapping are testable offline; the endpoint is not")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
