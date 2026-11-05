"""Review closure tests: add the missing question, promote, and it becomes findable.

The property that matters: **after the teacher transcribes the missing question and
promotes the version, retrieval returns it.** A "closed loop" that only flips a status
would leave the question still missing from search.

The gapped paper is produced by the fake OCR provider, so no vendor call is involved.
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

from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import identity  # noqa: E402
from app.tools import impl as tools_impl  # noqa: E402
from tests.support import provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


def search_ctx(owner_id, topic: str):
    return tools_impl.ToolContext(
        owner_id=owner_id,
        execution_id=uuid.uuid4(),
        step_key="search",
        spec={},
        requirement={"topic": topic, "sources": []},
        deps={},
    )


def gapped_pdf() -> bytes:
    """A PDF whose fake OCR text has questions 1, 2 and 4 — hole at 3."""
    from tests.pdf_fixture import minimal_pdf

    marker = (
        "FAKE_OCR:0.95|1.已知集合 A 与 B，求交集。\\n"
        "2.已知复数 z，求共轭。\\n"
        "4.已知向量 a 与 b，求数量积。"
    )
    return minimal_pdf([]) + b"\n%" + marker.encode("utf-8") + b"\n"


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    saved = {k: os.environ.get(k) for k in ("CHILON_OCR_PROVIDER",)}
    os.environ["CHILON_OCR_PROVIDER"] = "fake"
    try:
        async with db.system_session() as session:
            username = f"rev_{uuid.uuid4().hex[:8]}"
            owner = await identity.register(session, username, "review_password_1")
            issued = await identity.login(session, username, "review_password_1")
        headers = {"Authorization": f"Bearer {issued.token}"}

        print("1. a paper with a hole is held for review, and says why")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/knowledge/sources",
                headers=headers,
                files={"file": ("gap.pdf", gapped_pdf(), "application/pdf")},
                data={"title": "有缺题的卷子", "source_type": "gaokao_paper"},
            )
        body = r.json()
        check(body["lifecycle_status"] == "pending_review", f"held (got {body['lifecycle_status']})")
        check(body["review_reasons"] == ["numbering_gaps"], f"reason (got {body['review_reasons']})")
        version_id = body["document_version_id"]

        async with db.session_for(owner) as session:
            diag = (
                await session.execute(
                    text(
                        """
                        SELECT (SELECT count(*) FROM knowledge_sources WHERE owner_id = :o) AS sources,
                               (SELECT count(*) FROM knowledge_document_versions WHERE id = :v) AS versions,
                               (SELECT lifecycle_status FROM knowledge_document_versions WHERE id = :v) AS lifecycle,
                               (SELECT count(*) FROM knowledge_chunks WHERE document_version_id = :v) AS chunks,
                               (SELECT count(*) FROM knowledge_chunks c
                                 JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
                                 WHERE c.text_content ILIKE '%向量%') AS matching_anywhere
                        """
                    ),
                    {"o": owner, "v": uuid.UUID(version_id)},
                )
            ).first()
        print("    diag:", dict(diag._mapping))

        print("2. it is not retrievable while held")
        async with db.session_for(owner) as session:
            before = await tools_impl.knowledge_search(
                session, search_ctx(owner, "向量")
            )
        check(len(before["hits"]) == 0, f"not retrievable yet ({len(before['hits'])} hits)")

        print("3. the outline names the hole")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/knowledge/versions/{version_id}", headers=headers)
        outline = r.json()
        check(outline["gaps"] == [3], f"gap 3 reported (got {outline['gaps']})")
        check(outline["numbers"] == [1, 2, 4], f"numbers (got {outline['numbers']})")

        print("4. the page shows the hole and offers to fill it")
        cookies = {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/ui/login",
                data={"username": username, "password": "review_password_1"},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"UI login (got {r.status_code})")
            cookies = dict(client.cookies)
            r = await client.get("/ui/knowledge")
        check(r.status_code == 200, f"knowledge page renders (got {r.status_code})")
        check("缺第 3 题" in r.text, "it names the missing question")
        check("/ui/knowledge/questions" in r.text, "and offers a form to add it")
        check("/ui/knowledge/promote" in r.text, "and a button to confirm completeness")

        print("5. filling the hole from the page closes it")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies
        ) as client:
            r = await client.post(
                "/ui/knowledge/questions",
                data={
                    "version_id": version_id,
                    "number": "3",
                    "stem": "3.已知平面向量 a=(1,2)，b=(x,1)，若 a⊥b，求 x。",
                    "answer": "x=-2",
                },
                follow_redirects=False,
            )
        check(r.status_code == 303, f"the form submits (got {r.status_code})")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/knowledge/versions/{version_id}", headers=headers)
        outline = r.json()
        check(outline["numbers"] == [1, 2, 3, 4], f"numbers contiguous (got {outline['numbers']})")
        check(outline["gaps"] == [], f"no gap left (got {outline['gaps']})")

        print("5b. the same number cannot be added twice")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/knowledge/versions/{version_id}/questions",
                headers=headers,
                json={"number": 3, "stem": "重复"},
            )
        check(r.status_code == 422, f"duplicate refused (got {r.status_code})")

        print("6. confirming completeness on the page makes it searchable")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies
        ) as client:
            r = await client.post(
                "/ui/knowledge/promote", data={"version_id": version_id}, follow_redirects=False
            )
        check(r.status_code == 303, f"the button submits (got {r.status_code})")

        async with db.session_for(owner) as session:
            after = await tools_impl.knowledge_search(session, search_ctx(owner, "向量"))
        check(len(after["hits"]) >= 1, f"it is findable now ({len(after['hits'])} hits)")
        check(
            any("a⊥b" in (h.get("excerpt") or "") for h in after["hits"]),
            "the hit is the question the teacher typed",
        )

        async with db.session_for(owner) as session:
            all_runs = (
                await session.execute(
                    text(
                        "SELECT stage, status, metrics FROM knowledge_ingestion_runs "
                        "WHERE document_version_id = :v ORDER BY started_at"
                    ),
                    {"v": uuid.UUID(version_id)},
                )
            ).all()
        run = next((r for r in all_runs if r.stage == "index"), None)
        check(run is not None, f"the promotion is recorded (stages={[r.stage for r in all_runs]})")
        check(
            run.metrics.get("promoted_by") == "teacher",
            f"and says who decided (got {run.metrics.get('promoted_by')})",
        )

        print("7. promoting again is a no-op, not an error")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(f"/knowledge/versions/{version_id}/promote", headers=headers)
        check(r.status_code == 200 and r.json()["promoted"] is False, "second promote is a no-op")


        print("9. a mis-cut stem can be corrected from the page")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies
        ) as client:
            r = await client.get(f"/ui/knowledge/{version_id}")
            check(r.status_code == 200, f"the correction page renders (got {r.status_code})")
            check("校对题目" in r.text or "第 1 题" in r.text, "it lists the questions")
            r = await client.post(
                "/ui/knowledge/questions/update",
                data={
                    "version_id": version_id,
                    "number": "4",
                    "stem": "4.已知向量 a=(3,4)，求 a 的模长。",
                    "answer": "5",
                },
                follow_redirects=False,
            )
            check(r.status_code == 303, f"the correction submits (got {r.status_code})")

        async with db.session_for(owner) as session:
            corrected = await tools_impl.knowledge_search(session, search_ctx(owner, "模长"))
        check(len(corrected["hits"]) >= 1, f"the corrected stem is findable ({len(corrected['hits'])} hits)")
        check(
            any("模长" in (h.get("excerpt") or "") for h in corrected["hits"]),
            "search returns the corrected text, not the old one",
        )
        async with db.session_for(owner) as session:
            old = await tools_impl.knowledge_search(session, search_ctx(owner, "数量积"))
        check(
            all("数量积" not in (h.get("excerpt") or "") or "模长" in (h.get("excerpt") or "")
                for h in old["hits"]),
            "the old wording no longer matches on its own",
        )

        print("10. a block that is not a question can be deleted")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies
        ) as client:
            r = await client.post(
                "/ui/knowledge/questions/delete",
                data={"version_id": version_id, "number": "2"},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"delete submits (got {r.status_code})")

        async with db.session_for(owner) as session:
            gone = await tools_impl.knowledge_search(session, search_ctx(owner, "复数"))
        check(
            all("复数" not in (h.get("excerpt") or "") for h in gone["hits"]),
            "the deleted question is no longer returned by search",
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/knowledge/versions/{version_id}", headers=headers)
        outline = r.json()
        check(2 not in outline["numbers"], f"it is gone from the outline (got {outline['numbers']})")

        print("8. another teacher cannot touch this version")
        async with db.system_session() as session:
            other_name = f"rev_other_{uuid.uuid4().hex[:6]}"
            await identity.register(session, other_name, "other_password_1")
            other = await identity.login(session, other_name, "other_password_1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/knowledge/versions/{version_id}/questions",
                headers={"Authorization": f"Bearer {other.token}"},
                json={"number": 9, "stem": "别人的题"},
            )
            check(r.status_code in (404, 422), f"the other teacher is refused (got {r.status_code})")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("PASS: a hole can be filled, promoted, and then actually searched")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
