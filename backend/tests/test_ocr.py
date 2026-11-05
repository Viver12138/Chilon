"""OCR tests: the plumbing, not the engine.

A real OCR engine cannot be asserted on — it changes between versions and disagrees
about `sin²x`. What can be asserted, and is what actually breaks in production:

* with no provider, a scan is still refused with the same honest reason;
* with a provider, the scan becomes text, is recorded as an `ocr` run, and carries
  engine + version;
* a low-confidence scan lands in `pending_review` and is **not retrievable**;
* the cloud provider cannot be reached without an endpoint and key.

The fake provider reads a marker from the PDF's own bytes, so each case is exact.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import settings as config  # noqa: E402
from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import identity, ocr  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.pdf_fixture import minimal_pdf  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


def scanned_pdf(marker: str) -> bytes:
    """A PDF with no text layer, carrying a marker the fake provider can read."""
    return minimal_pdf([]) + b"\n%" + marker.encode("utf-8") + b"\n"


def search_ctx(owner_id, requirement):
    return tools_impl.ToolContext(
        owner_id=owner_id,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement=requirement,
        deps={},
    )


async def upload(client, headers, name: str, data: bytes, title: str) -> dict:
    r = await client.post(
        "/knowledge/sources",
        headers=headers,
        files={"file": (name, data, "application/pdf")},
        data={"title": title, "source_type": "mock_exam"},
    )
    return {"status": r.status_code, **r.json()}


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    saved_env = {k: os.environ.get(k) for k in ("CHILON_OCR_PROVIDER",)}
    try:
        async with db.system_session() as session:
            username = f"ocr_{uuid.uuid4().hex[:8]}"
            owner = await identity.register(session, username, "ocr_password_1")
            issued = await identity.login(session, username, "ocr_password_1")
        headers = {"Authorization": f"Bearer {issued.token}"}

        print("1. a provider is off by default, and the scan is refused")
        os.environ["CHILON_OCR_PROVIDER"] = "none"
        check(ocr.build() is None, "no provider is built when OCR is off")
        check(config.load().ocr_configured is False, "and the settings agree")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = await upload(client, headers, "scan.pdf", scanned_pdf(""), "扫描件")
        check(body["lifecycle_status"] == "failed", f"refused (got {body['lifecycle_status']})")
        check("OCR" in (body["parse_detail"] or ""), "the reason still mentions OCR")

        print("2. with a provider, the scan becomes text and is recorded as an OCR run")
        os.environ["CHILON_OCR_PROVIDER"] = "fake"
        marker = "FAKE_OCR:0.95|1. 已知 f(x)=sin(2x+π/3)，求最小正周期。\\n2. 化简 sin²x+cos²x。"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = await upload(client, headers, "scan2.pdf", scanned_pdf(marker), "扫描件 2")
        check(body["lifecycle_status"] == "indexed", f"indexed (got {body['lifecycle_status']})")
        check(body["questions"] == 2, f"two questions recovered (got {body['questions']})")
        check(body["ocr"] is not None, "the response says OCR was used")
        check(body["ocr"]["engine"] == "fake", f"engine recorded (got {body['ocr']})")

        async with db.session_for(owner) as session:
            run = (
                await session.execute(
                    text(
                        """
                        SELECT stage, status, tool_version FROM knowledge_ingestion_runs
                        WHERE document_version_id = :v ORDER BY started_at DESC LIMIT 1
                        """
                    ),
                    {"v": uuid.UUID(body["document_version_id"])},
                )
            ).all()
        stages = {r.stage for r in run if r.status == "succeeded"}
        check("ocr" in stages, f"the run is recorded under the ocr stage (got {stages})")
        check(
            any(r.tool_version for r in run),
            "the engine version is recorded, so a different OCR can explain a different result",
        )

        print("3. a high-confidence scan is retrievable")
        async with db.session_for(owner) as session:
            found = await tools_impl.knowledge_search(
                session, search_ctx(owner, {"topic": "最小正周期", "sources": []})
            )
        check(len(found["hits"]) >= 1, f"retrieval found {len(found['hits'])} hit(s)")

        print("4. a low-confidence scan is held for review, not indexed")
        marker_low = "FAKE_OCR:0.30|1. 模糊的题干文字。\\n2. 另一道模糊的题。"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = await upload(client, headers, "blur.pdf", scanned_pdf(marker_low), "模糊扫描")
        check(
            body["lifecycle_status"] == "pending_review",
            f"held for review (got {body['lifecycle_status']})",
        )
        check(body["needs_review"] is True, "the response says review is needed")
        async with db.session_for(owner) as session:
            hidden = await tools_impl.knowledge_search(
                session, search_ctx(owner, {"topic": "模糊", "sources": []})
            )
        check(len(hidden["hits"]) == 0, f"and it is not retrievable (got {len(hidden['hits'])})")

        print("5. the cloud provider cannot be reached by leaving config empty")
        os.environ["CHILON_OCR_PROVIDER"] = "cloud"
        os.environ.pop("CHILON_OCR_CLOUD_ENDPOINT", None)
        os.environ.pop("CHILON_OCR_CLOUD_KEY", None)
        try:
            ocr.build()
            check(False, "the cloud provider built without credentials")
        except ocr.OcrUnavailable as exc:
            check("CHILON_OCR_CLOUD" in str(exc), f"refused with a clear reason ({str(exc)[:60]})")

        print("6. an unknown provider name fails loudly, not silently")
        os.environ["CHILON_OCR_PROVIDER"] = "magic"
        try:
            ocr.build()
            check(False, "an unknown provider was accepted")
        except ocr.OcrUnavailable as exc:
            check("unknown OCR provider" in str(exc), "unknown provider refused")
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: OCR is opt-in, recorded, and cannot silently pollute the knowledge base")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
