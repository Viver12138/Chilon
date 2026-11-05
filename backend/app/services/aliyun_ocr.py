"""Aliyun education OCR: request signing and a shape-adaptive response reader.

Two halves, with very different confidence levels, kept apart on purpose:

* **The request is implemented to the documented contract.** Endpoint, action,
  parameters (`body` binary, `CutType`, `ImageType`, `Subject`, `OutputOricoord`) and
  the ACS3-HMAC-SHA256 signature are written from Aliyun's specification. The signature
  is unit-tested for determinism, which is all that can be proven without credentials.
* **The response shape is not documented where this was written.** The docs truncate
  `Data` to `{"p…`. So the reader looks for question-shaped lists generically and
  **fails loudly with the keys it actually saw** when it cannot find them. Guessing a
  structure and returning empty questions would look like "this paper had no questions".

Nothing here has been executed against the real endpoint: there are no credentials in
this environment. That is recorded in the design log rather than implied by green tests.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

OCR_HOST = "ocr-api.cn-hangzhou.aliyuncs.com"
OCR_VERSION = "2021-07-07"
ACTION_CUT = "RecognizeEduPaperCut"
# Full-page text: no segmentation, used as the fallback when cutting yields nothing.
ACTION_PAGE = "RecognizeEduPaperOcr"
# Fine-grained structure: adds section/topic labels on top of cutting.
ACTION_STRUCTED = "RecognizeEduPaperStructed"

EDUCATION_ACTIONS = {
    ACTION_CUT: "试卷切题：按题切分，返回题干/选项/答案",
    ACTION_PAGE: "整页识别：整页文字与公式，不切题（兜底）",
    ACTION_STRUCTED: "精细版结构化：切题 + 标题/主题等版面标签",
}

# keys that plausibly carry the question text, most specific first
TEXT_KEYS = ("Text", "text", "Content", "content", "Stem", "stem", "Question", "question", "Title")
OPTION_KEYS = ("OptionList", "Options", "options", "option_list")


@dataclass
class PaperQuestion:
    """One question as the vendor segmented it."""

    stem: str
    options: list[str] = field(default_factory=list)
    answer: str | None = None
    page: int | None = None

    def as_text(self) -> str:
        parts = [self.stem]
        if self.options:
            parts.append(" ".join(self.options))
        return "\n".join(part for part in parts if part)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_query(params: dict[str, str]) -> str:
    from urllib.parse import quote

    return "&".join(
        f"{quote(key, safe='~')}={quote(value, safe='~')}" for key, value in sorted(params.items())
    )


def sign_request(
    *,
    access_key_id: str,
    access_key_secret: str,
    action: str,
    params: dict[str, str],
    body: bytes,
    timestamp: str,
) -> dict[str, str]:
    """Build the ACS3-HMAC-SHA256 headers.

    Signature layout (Aliyun "V3" signing):

        ACS3-HMAC-SHA256
        <method>\\n<canonical uri>\\n<canonical query>\\n<canonical headers>\\n
        <signed headers>\\n<hashed payload>

    The hash of the payload is over the **body bytes**, which is why the image is passed
    as binary rather than base64: base64 would change the signature and the size limit.
    """
    payload_hash = _sha256_hex(body)
    headers = {
        "host": OCR_HOST,
        "x-acs-action": action,
        "x-acs-version": OCR_VERSION,
        "x-acs-date": timestamp,
        "x-acs-signature-nonce": _nonce(),
        "x-acs-content-sha256": payload_hash,
    }
    canonical_headers = "".join(
        f"{key.lower()}:{value.strip()}\n" for key, value in sorted(headers.items())
    )
    signed_headers = ";".join(sorted(key.lower() for key in headers))
    canonical_request = "\n".join(
        ["POST", "/", canonical_query(params), canonical_headers, signed_headers, payload_hash]
    )
    string_to_sign = "\n".join(
        ["ACS3-HMAC-SHA256", _sha256_hex(canonical_request.encode("utf-8"))]
    )
    signature = hmac.new(
        access_key_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return {
        **{key: value for key, value in headers.items()},
        "Authorization": (
            f"ACS3-HMAC-SHA256 Credential={access_key_id},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        ),
        "x-acs-signature-nonce": headers["x-acs-signature-nonce"],
        "content-type": "application/octet-stream",
    }


def _nonce() -> str:
    import uuid

    return uuid.uuid4().hex


def now_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── response shape ────────────────────────────────────────────────────────────


class ShapeUnknown(Exception):
    """The payload did not contain anything recognisable as a question list."""


def _text_of(item: dict[str, Any]) -> str:
    for key in TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _options_of(item: dict[str, Any]) -> list[str]:
    for key in OPTION_KEYS:
        value = item.get(key)
        if isinstance(value, list):
            out = []
            for option in value:
                if isinstance(option, str):
                    out.append(option.strip())
                elif isinstance(option, dict):
                    text = _text_of(option) or str(option.get("Value") or "").strip()
                    if text:
                        out.append(text)
            if out:
                return out
    return []


def extract_questions(payload: Any, *, page: int | None = None) -> list[PaperQuestion]:
    """Find question-shaped items anywhere in the response.

    Deliberately not tied to one key path: the vendor's `Data` shape is not part of the
    contract this code could verify. What it will not do is return an empty list when
    the payload simply had a different shape — that case raises `ShapeUnknown` so the
    failure is visible at upload time instead of becoming an empty knowledge base.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ShapeUnknown(f"Data is not JSON: {exc}") from exc

    candidates: list[dict[str, Any]] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            if _text_of(node):
                candidates.append(node)
                return
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(payload)

    questions: list[PaperQuestion] = []
    for item in candidates:
        stem = _text_of(item)
        if not stem:
            continue
        answer = None
        for key in ("Answer", "answer", "Analysis", "analysis"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                answer = value.strip()
                break
        questions.append(
            PaperQuestion(
                stem=stem,
                options=_options_of(item),
                answer=answer,
                page=page,
            )
        )

    if not questions:
        seen = sorted(payload.keys())[:12] if isinstance(payload, dict) else type(payload).__name__
        raise ShapeUnknown(f"no question-shaped items found; top-level keys were {seen}")
    return questions


def _ignore_b64(value: str) -> bytes:
    """Kept so an operator can see that base64 is available if a variant needs it."""
    return base64.b64decode(value)


_ = _ignore_b64

def describe_shape(node: Any, *, depth: int = 0, max_depth: int = 3) -> str:
    """Describe a JSON payload compactly, so an operator can see what came back.

    This exists because the vendor's response shape is not documented where this code
    was written. Rather than guess keys, the smoke tool prints this and the reader is
    adjusted from evidence.
    """
    indent = "  " * depth
    if depth >= max_depth:
        return f"{indent}…"
    if isinstance(node, dict):
        lines = []
        for key, value in node.items():
            if isinstance(value, dict):
                lines.append(f"{indent}{key}: object")
                lines.append(describe_shape(value, depth=depth + 1, max_depth=max_depth))
            elif isinstance(value, list):
                first = value[0] if value else None
                lines.append(f"{indent}{key}: list[{len(value)}]")
                if first is not None:
                    lines.append(describe_shape(first, depth=depth + 1, max_depth=max_depth))
            elif isinstance(value, str):
                preview = value[:60].replace("\n", " ")
                lines.append(f"{indent}{key}: str({len(value)}) {preview!r}")
            else:
                lines.append(f"{indent}{key}: {type(value).__name__} {value!r}"[:110])
        return "\n".join(lines)
    if isinstance(node, list):
        if not node:
            return f"{indent}[]"
        lines = [f"{indent}list[{len(node)}] of {type(node[0]).__name__}"]
        lines.append(describe_shape(node[0], depth=depth + 1, max_depth=max_depth))
        return "\n".join(lines)
    return f"{indent}{type(node).__name__} {node!r}"[:110]

def decode_data(payload: Any) -> Any:
    """Unwrap the `Data` field, which the vendor returns as a JSON string.

    Handled here rather than in the provider so the smoke tool and the provider agree
    about what "the response" is. A payload that is already an object is passed
    through: the docs show `Data` as a string, but a variant must not break the reader.
    """
    if not isinstance(payload, dict):
        return payload
    data = payload.get("Data", payload)
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data

def extract_page_text(payload: Any) -> str:
    """Collect the text out of a full-page OCR payload.

    `RecognizeEduPaperOcr` does not segment, so there is nothing to map onto
    questions: it returns text (and word boxes). The reader gathers the string fields
    in order and joins them. Same honesty rule as `extract_questions`: if there is no
    text at all it raises rather than returning `""`, because empty text looks like a
    blank page.
    """
    data = decode_data(payload)

    chunks: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and len(value.strip()) >= 2 and key.lower() not in (
                    "requestid",
                    "errormessage",
                    "errorcode",
                ):
                    chunks.append(value.strip())
                else:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(data)
    text = "\n".join(chunks).strip()
    if not text:
        raise ShapeUnknown("no text found in the page payload")
    return text
