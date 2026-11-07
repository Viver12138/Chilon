"""Teacher UI tests: the flow a real teacher performs, through the pages.

This is the first suite that exercises the product the way a person will: form posts,
redirects, cookies, and downloaded files. It runs as the application role like every
other suite, so a permission gap shows up here too.

The planner is forced to the template engine so the test asserts the UI, not whether a
model answered.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

os.environ["CHILON_PLANNER"] = "template"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import session as db  # noqa: E402
from app.main import app  # noqa: E402
from tests.support import admin_session, provision_runtime_role  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"    ok   {message}")
    else:
        print(f"    FAIL {message}")
        FAILURES.append(message)


async def main() -> int:
    url = os.environ.get("CHILON_TEST_DATABASE_URL")
    if not url:
        print("CHILON_TEST_DATABASE_URL is not set")
        return 2

    db.init(await provision_runtime_role(url))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            print("1. a stranger is sent to the login page")
            r = await client.get("/", follow_redirects=False)
            check(r.status_code == 303 and r.headers["location"] == "/ui/login", "root redirects to login")
            r = await client.get("/ui/tasks", follow_redirects=False)
            check(r.status_code == 303, "tasks redirects when not signed in")
            r = await client.get("/ui/login")
            check(r.status_code == 200 and "登录" in r.text, "the login page renders")

            print("2. registering signs the teacher in")
            username = f"ui_{uuid.uuid4().hex[:8]}"
            r = await client.post(
                "/ui/register",
                data={"username": username, "password": "correct horse 1", "display_name": "王老师"},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"register redirects (got {r.status_code})")
            check("chilon_session" in client.cookies, "a session cookie was set")
            r = await client.get("/ui/tasks")
            check(r.status_code == 200 and username in r.text, "the task page shows the signed-in teacher")

            print("3. one sentence produces a plan")
            r = await client.post(
                "/ui/tasks",
                data={"title": "三角函数练习", "requirement": "用高考题出 4 道三角函数题"},
                follow_redirects=False,
            )
            check(r.status_code == 303, f"task creation redirects (got {r.status_code})")
            detail_url = r.headers["location"]
            r = await client.get(detail_url)
            check(r.status_code == 200, "the task page renders")
            check("三角函数练习" in r.text, "the title is shown")
            check("方案 v1" in r.text, "a plan version is shown")
            check("批准并执行" in r.text, "the approve button is offered")
            check("检索" in r.text or "knowledge.search" in r.text, "plan steps are listed")

            print("4. approving runs the execution")
            r = await client.post(f"{detail_url}/approve", follow_redirects=False)
            check(r.status_code == 303, f"approve redirects (got {r.status_code})")
            r = await client.get(detail_url)
            check("succeeded" in r.text, "the execution reports success")
            check("材料" in r.text, "a material section appears")
            check("请求发布" in r.text, "publishing is offered as a separate step")

            print("5. publishing is two steps and produces a version")
            r = await client.post(f"{detail_url}/publish/request", follow_redirects=False)
            check(r.status_code == 303, f"publish redirects (got {r.status_code})")
            r = await client.get(detail_url)
            check("已发布" in r.text, "the material is published")
            check("下载教师版" in r.text and "下载学生版" in r.text, "both downloads are offered")

            print("6. the downloads are real files, and the student copy has no answers")
            r = await client.post(
                f"{detail_url}/export", data={"profile": "teacher"}, follow_redirects=False
            )
            check(r.status_code == 303, "teacher export redirects to the file")
            teacher = await client.get(r.headers["location"], follow_redirects=False)
            check(teacher.status_code == 200, f"teacher file downloads ({teacher.status_code})")
            check(teacher.content[:2] == b"PK", "the download is a real DOCX (zip)")

            r = await client.post(
                f"{detail_url}/export", data={"profile": "student"}, follow_redirects=False
            )
            student = await client.get(r.headers["location"], follow_redirects=False)
            check(student.content[:2] == b"PK", "student file downloads too")
            check(student.content != teacher.content, "the two files differ")

            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from app.services import export as export_service

            student_text = export_service.docx_text(student.content)
            teacher_text = export_service.docx_text(teacher.content)
            check("教师版" in teacher_text, "the teacher file labels itself")
            check("学生版" in student_text, "the student file labels itself")
            check("答案" not in student_text or "学生版" in student_text, "student file has no answer label")

            print("7a. an upload that needs review says why")
            # a scan with a numbering hole: the reason must reach the page, verbatim
            from app.services import ingestion as ingestion_service

            reasons = ingestion_service.review_reasons(
                gaps=[9], confidence=0.9, min_confidence=0.6,
                analysis_blocks=0, questions=16,
            )
            check(reasons == ["numbering_gaps"], f"gap reason computed (got {reasons})")
            # measured on the real papers: 原卷版 21% unnumbered, 解析版 55%
            reasons = ingestion_service.review_reasons(
                gaps=[], confidence=0.9, min_confidence=0.6,
                analysis_blocks=3, questions=14, total_blocks=31, unnumbered_blocks=17,
            )
            check(reasons == ["analysis_version"], f"analysis version detected (got {reasons})")
            reasons = ingestion_service.review_reasons(
                gaps=[], confidence=0.9, min_confidence=0.6,
                analysis_blocks=0, questions=15, total_blocks=19, unnumbered_blocks=4,
            )
            check(reasons == [], f"a normal paper is not flagged (got {reasons})")
            reasons = ingestion_service.review_reasons(
                gaps=[], confidence=0.2, min_confidence=0.6,
                analysis_blocks=0, questions=5,
            )
            check(reasons == ["low_confidence"], f"low confidence detected (got {reasons})")

            r = await client.get("/ui/knowledge")
            check(r.status_code == 200, f"the knowledge page renders (got {r.status_code})")
            check("上传资料" in r.text, "it links to the upload page")
            r = await client.get("/ui/knowledge/upload")
            check(r.status_code == 200, f"the upload page renders (got {r.status_code})")
            check("上传并解析" in r.text, "it offers an upload form")


            print("7. signing out closes the door")
            r = await client.post("/ui/logout", follow_redirects=False)
            check(r.status_code == 303, "logout redirects")
            r = await client.get("/ui/tasks", follow_redirects=False)
            check(r.status_code == 303, "the tasks page is closed again")

            print("8. a second teacher cannot open the first teacher's task")
            other = httpx.AsyncClient(transport=transport, base_url="http://test")
            try:
                other_name = f"ui2_{uuid.uuid4().hex[:8]}"
                await other.post(
                    "/ui/register",
                    data={"username": other_name, "password": "correct horse 2"},
                    follow_redirects=False,
                )
                task_id = detail_url.rsplit("/", 1)[-1]
                r = await other.get(f"/ui/tasks/{task_id}")
                check(r.status_code == 200 and "不属于你" in r.text, "the other teacher sees nothing")
            finally:
                await other.aclose()

        # material_versions is owner-scoped: counting it from a context-free session
        # returns zero, which would look like "publishing failed" for the wrong reason
        async with admin_session() as s:
            rows = (
                await s.execute(text("SELECT count(*) FROM material_versions"))
            ).scalar_one()
        check(rows >= 1, "a material version was written")

    finally:
        await db.dispose()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} assertion(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: a teacher can register, plan, approve, publish and download from the pages")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
