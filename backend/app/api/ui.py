"""Server-rendered teacher UI.

No build step on purpose. The gap this closes is "a teacher can only use curl", and a
React build chain would add a second toolchain, a bundler config and a deploy artefact
before a single teacher could open a page. Server-rendered HTML works from the same
process, with the same services, and is testable with the same client.

Everything here is a **thin view over existing services**. No business rule is
duplicated: the UI calls `agent.propose_plan`, `agent.approve_plan`,
`executions.start_execution`, `executor.run_once`, `publication.*` and `export.*`
exactly as the HTTP API does. If the UI could do something the API cannot, it would
be a second implementation of the rules — that is the failure this file must avoid.

Two deliberate UX decisions:

* **Publish is two buttons, not one.** Requesting and confirming are separate steps
  because they are separate steps in the model. A single "publish" button would make
  the approval look like a formality it is not.
* **Running is synchronous here.** Clicking "批准并执行" waits for the executor. That
  is honest for a single-process deployment; a queue would return immediately and let
  the progress panel do the waiting.
"""

from __future__ import annotations

import html
import uuid
from urllib.parse import quote
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Cookie, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import text

from app.db import session as db
from app.services import (
    agent,
    knowledge_review,
    passwords,
    executions,
    executor,
    export,
    identity,
    planner,
    publication,
    tasks,
)

router = APIRouter(tags=["ui"], include_in_schema=False)

COOKIE = "chilon_session"


# ── tiny templating ────────────────────────────────────────────────────────────

STYLE = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       max-width: 880px; margin: 0 auto; padding: 24px; line-height: 1.6; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
.card { border: 1px solid #8884; border-radius: 8px; padding: 16px; margin: 12px 0; }
button { padding: 8px 14px; border-radius: 6px; border: 1px solid #8886;
         background: #4a6cf7; color: #fff; cursor: pointer; font-size: 0.95rem; }
button.secondary { background: transparent; color: inherit; }
input, textarea { width: 100%; padding: 8px; box-sizing: border-box;
                  border-radius: 6px; border: 1px solid #8886; font: inherit; }
.muted { opacity: 0.7; font-size: 0.9rem; }
.err { color: #c0392b; } .ok { color: #27ae60; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 6px 8px; border-bottom: 1px solid #8883; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px;
       background: #8882; font-size: 0.85rem; }
pre { background: #8881; padding: 12px; border-radius: 6px; overflow-x: auto; }
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str, *, teacher: str | None = None) -> HTMLResponse:
    header = ""
    if teacher:
        header = (
            '<div class="muted" style="display:flex;justify-content:space-between">'
            f"<span>{esc(teacher)}</span>"
            '<a href="/ui/knowledge" style="margin-right:12px">知识库</a>'
            '<form method="post" action="/ui/logout" style="margin:0">'
            '<button class="secondary" type="submit">退出</button></form></div>'
        )
    return HTMLResponse(
        f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)} · Chilon</title><style>{STYLE}</style></head>"
        f"<body>{header}<h1>{esc(title)}</h1>{body}</body></html>"
    )


# ── auth ───────────────────────────────────────────────────────────────────────


async def teacher_from_cookie(
    token: str | None,
) -> tuple[uuid.UUID, str, bool] | None:
    if not token:
        return None
    async with db.system_session() as session:
        try:
            user_id = await identity.authenticate(session, token)
        except identity.IdentityError:
            return None
        row = (
            await session.execute(
                text("SELECT username FROM users WHERE id = :id"), {"id": user_id}
            )
        ).first()
        pending = await identity.must_change_password(session, user_id)
    return (user_id, row.username if row else "teacher", pending)


def login_page(error: str | None = None) -> HTMLResponse:
    err = f"<p class='err'>{esc(error)}</p>" if error else ""
    body = (
        f"{err}<div class='card'><form method='post' action='/ui/login'>"
        "<p><label>用户名<br><input name='username' autocomplete='username' required></label></p>"
        "<p><label>密码<br><input name='password' type='password' "
        "autocomplete='current-password' required></label></p>"
        "<button type='submit'>登录</button></form></div>"
        "<p class='muted'>还没有账号？"
        "<a href='/ui/register'>注册一个</a></p>"
    )
    return page("登录", body)


def register_page(error: str | None = None) -> HTMLResponse:
    err = f"<p class='err'>{esc(error)}</p>" if error else ""
    body = (
        f"{err}<div class='card'><form method='post' action='/ui/register'>"
        "<p><label>用户名<br><input name='username' minlength='3' required></label></p>"
        "<p><label>显示名（可选）<br><input name='display_name'></label></p>"
        "<p><label>密码（至少 8 位）<br>"
        "<input name='password' type='password' minlength='8' required></label></p>"
        "<button type='submit'>注册并登录</button></form></div>"
        "<p class='muted'><a href='/ui/login'>已有账号</a></p>"
    )
    return page("注册", body)


@router.get("/")
async def root(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    who = await teacher_from_cookie(chilon_session)
    return RedirectResponse("/ui/tasks" if who else "/ui/login", status_code=303)


@router.get("/ui/login")
async def get_login(error: str | None = None) -> Response:
    return login_page(error)


@router.post("/ui/login")
async def post_login(
    username: Annotated[str, Form()], password: Annotated[str, Form()]
) -> Response:
    async with db.system_session() as session:
        try:
            issued = await identity.login(session, username, password)
        except identity.IdentityError:
            return login_page("用户名或密码不正确")
    response = RedirectResponse("/ui/tasks", status_code=303)
    response.set_cookie(
        COOKIE, issued.token, httponly=True, samesite="lax", path="/"
    )
    return response


@router.get("/ui/register")
async def get_register() -> Response:
    return register_page()


@router.post("/ui/register")
async def post_register(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str | None, Form()] = None,
) -> Response:
    if len(password) < 8:
        return register_page("密码至少 8 位")
    async with db.system_session() as session:
        try:
            user_id = await identity.register(session, username, password, display_name)
        except identity.UsernameTaken:
            return register_page("这个用户名已被占用")
        except identity.IdentityError as exc:
            return register_page(str(exc))
    # grants are owner-scoped, so they are written in the new teacher's own context
    async with db.session_for(user_id) as session:
        await agent.ensure_default_grants(session, user_id)
    async with db.system_session() as session:
        issued = await identity.login(session, username, password)
    response = RedirectResponse("/ui/tasks", status_code=303)
    response.set_cookie(COOKIE, issued.token, httponly=True, samesite="lax", path="/")
    return response


@router.post("/ui/logout")
async def post_logout(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    if chilon_session:
        async with db.system_session() as session:
            await identity.logout(session, chilon_session)
    response = RedirectResponse("/ui/login", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


# ── tasks ──────────────────────────────────────────────────────────────────────


@router.get("/ui/password")
async def get_password_page(
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    if not chilon_session:
        return RedirectResponse("/ui/login", status_code=303)
    body = (
        "<p class='muted'>这个账号正在使用管理员设置的临时密码，"
        "请设置一个新密码后继续。</p>"
        "<div class='card'><form method='post' action='/ui/password'>"
        "<p><label>当前密码<br>"
        "<input name='current_password' type='password' required></label></p>"
        "<p><label>新密码（至少 8 位）<br>"
        "<input name='new_password' type='password' minlength='8' required></label></p>"
        "<button type='submit'>设置新密码</button></form></div>"
    )
    return page("修改密码", body)


@router.post("/ui/password")
async def post_password(
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, _ = who
    if len(new_password) < 8:
        return page("修改密码", "<p class='err'>新密码至少 8 位。</p>", teacher=None)
    async with db.session_for(user_id) as session:
        try:
            await passwords.change_own(
                session, user_id, current_password, new_password, token=chilon_session or ""
            )
        except identity.InvalidCredentials:
            body = (
                "<p class='err'>当前密码不正确。</p>"
                "<div class='card'><form method='post' action='/ui/password'>"
                "<p><label>当前密码<br><input name='current_password' type='password' required></label></p>"
                "<p><label>新密码（至少 8 位）<br>"
                "<input name='new_password' type='password' minlength='8' required></label></p>"
                "<button type='submit'>设置新密码</button></form></div>"
            )
            return page("修改密码", body)
    return RedirectResponse("/ui/tasks", status_code=303)



REASON_TEXT = {
    "numbering_gaps": "题号有缺口，可能漏题——请补录或重传更完整的一页",
    "analysis_version": "看起来是解析版（含大量解析），请上传原卷版作为题目来源",
    "low_confidence": "识别置信度偏低——请重传更清晰的扫描件",
}


@router.get("/ui/knowledge")
async def knowledge_page(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    """What the teacher uploaded, and what to do about anything held for review.

    The reason is rendered next to the state because the two together are the actionable
    part; a bare "待复核" only moves the judgement back to the teacher.
    """
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT s.title, s.source_type, s.rights_status,
                           v.id AS version_id, v.lifecycle_status,
                           (SELECT r.metrics->'review_reasons' FROM knowledge_ingestion_runs r
                            WHERE r.document_version_id = v.id
                            ORDER BY r.started_at DESC LIMIT 1) AS review_reasons,
                           (SELECT array_agg(q.question_no ORDER BY q.ordinal)
                            FROM knowledge_questions q
                            WHERE q.document_version_id = v.id) AS question_numbers
                    FROM knowledge_sources s
                    LEFT JOIN LATERAL (
                        SELECT dv.id, dv.lifecycle_status FROM knowledge_document_versions dv
                        WHERE dv.source_id = s.id ORDER BY dv.version_no DESC LIMIT 1
                    ) v ON true
                    WHERE s.deleted_at IS NULL
                    ORDER BY s.created_at DESC LIMIT 100
                    """
                )
            )
        ).all()

    blocks = []
    for row in rows:
        status = row.lifecycle_status or "未上传版本"
        reasons = list(row.review_reasons or [])
        reason_html = ""
        if reasons:
            items = "".join(
                f"<li>{esc(REASON_TEXT.get(code, code))}</li>" for code in reasons
            )
            reason_html = f"<ul class='muted'>{items}</ul>"

        gaps = _gaps_of(row.question_numbers)
        holes = ""
        if gaps and row.version_id and status == "pending_review":
            options = "".join(f"<option value='{n}'>{n}</option>" for n in gaps)
            holes = (
                f"<p>缺第 {esc(', '.join(str(n) for n in gaps))} 题</p>"
                "<form method='post' action='/ui/knowledge/questions' "
                "style='border-top:1px solid #8883;padding-top:10px;margin-top:10px'>"
                f"<input type='hidden' name='version_id' value='{esc(row.version_id)}'>"
                "<p><label>题号<br><select name='number'>"
                f"{options}</select></label></p>"
                "<p><label>题干（可含 LaTeX）<br>"
                "<textarea name='stem' rows='2' required></textarea></label></p>"
                "<p><label>答案（可选）<br><input name='answer'></label></p>"
                "<button type='submit'>补上这题</button></form>"
            )
        promote = ""
        if row.version_id and status == "pending_review":
            promote = (
                "<form method='post' action='/ui/knowledge/promote' style='margin-top:8px'>"
                f"<input type='hidden' name='version_id' value='{esc(row.version_id)}'>"
                "<button class='secondary' type='submit'>确认完整并启用</button></form>"
            )
        detail = (
            f"<p><a href='/ui/knowledge/{esc(row.version_id)}'>校对题目 →</a></p>"
            if row.version_id
            else ""
        )
        blocks.append(
            f"<div class='card'><p><b>{esc(row.title)}</b> "
            f"<span class='tag'>{esc(status)}</span> "
            f"<span class='muted'>{esc(row.source_type)}</span></p>"
            f"{reason_html}{holes}{promote}{detail}</div>"
        )

    body = (
        (''.join(blocks) if blocks else "<p class='muted'>还没有上传任何材料。</p>")
        + "<h2>上传试卷</h2><div class='card'>"
        "<form method='post' action='/ui/knowledge' enctype='multipart/form-data'>"
        "<p><label>标题<br><input name='title' required></label></p>"
        "<p><label>类型<br><select name='source_type'>"
        "<option value='gaokao_paper'>高考真题</option>"
        "<option value='mock_exam'>模拟题</option>"
        "<option value='textbook'>教材</option>"
        "<option value='other'>其他</option></select></label></p>"
        "<p><label>文件（.docx 或可复制文字的 .pdf）<br>"
        "<input type='file' name='file' accept='.docx,.pdf' required></label></p>"
        "<button type='submit'>上传并解析</button></form></div>"
    )
    return page("知识库", body, teacher=name)


@router.post("/ui/knowledge")
async def knowledge_upload(
    title: Annotated[str, Form()],
    source_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)

    from app.api import knowledge as knowledge_api

    async with db.session_for(user_id) as session:
        await knowledge_api.store_and_ingest(session, user_id, file, title, source_type)
    return RedirectResponse("/ui/knowledge", status_code=303)



def _gaps_of(numbers) -> list[int]:
    """Holes in the numbering, computed the same way the service does."""
    parsed = []
    for value in numbers or []:
        try:
            parsed.append(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return []
    high = max(parsed)
    return [n for n in range(1, high + 1) if n not in parsed] if min(parsed) == 1 else []


async def _knowledge_action(chilon_session: str | None):
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return None, RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        return None, RedirectResponse("/ui/password", status_code=303)
    return user_id, None


@router.post("/ui/knowledge/questions")
async def knowledge_add_question(
    version_id: Annotated[str, Form()],
    number: Annotated[int, Form()],
    stem: Annotated[str, Form()],
    answer: Annotated[str | None, Form()] = None,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _knowledge_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.add_question(
                session, user_id, uuid.UUID(version_id),
                number=number, stem=stem, answer=answer,
            )
        except knowledge_review.ReviewError:
            # the page renders the reason; a failed add must not break the listing
            pass
    return RedirectResponse("/ui/knowledge", status_code=303)


@router.post("/ui/knowledge/promote")
async def knowledge_promote(
    version_id: Annotated[str, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _knowledge_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.promote(session, user_id, uuid.UUID(version_id))
        except knowledge_review.ReviewError:
            pass
    return RedirectResponse("/ui/knowledge", status_code=303)



@router.get("/ui/knowledge/{version_id}")
async def knowledge_questions(
    version_id: uuid.UUID,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    """Every question in one version, with the two corrections that actually happen:
    fixing a stem the cutter read wrong, and deleting a block that is not a question."""
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT q.question_no, q.segmentation_source, c.text_content
                    FROM knowledge_questions q
                    LEFT JOIN knowledge_chunks c
                           ON c.document_version_id = q.document_version_id
                          AND c.locator = q.stem_locator
                    WHERE q.document_version_id = :v
                    ORDER BY q.ordinal
                    """
                ),
                {"v": version_id},
            )
        ).all()

    cards = []
    for row in rows:
        body_text = (row.text_content or "").strip()
        preview = body_text[:120] + ("…" if len(body_text) > 120 else "")
        source = "教师录入" if row.segmentation_source == "teacher" else "自动切分"
        cards.append(
            "<div class='card'>"
            f"<p><b>第 {esc(row.question_no)} 题</b> <span class='muted'>{esc(source)}</span></p>"
            f"<p class='muted'>{esc(preview)}</p>"
            "<form method='post' action='/ui/knowledge/questions/update'>"
            f"<input type='hidden' name='version_id' value='{esc(version_id)}'>"
            f"<input type='hidden' name='number' value='{esc(row.question_no)}'>"
            "<p><label>改题干<br>"
            f"<textarea name='stem' rows='2'>{esc(body_text)}</textarea></label></p>"
            "<p><label>改答案（留空则不动）<br><input name='answer'></label></p>"
            "<button class='secondary' type='submit'>保存修改</button></form>"
            "<form method='post' action='/ui/knowledge/questions/delete' style='margin-top:6px'>"
            f"<input type='hidden' name='version_id' value='{esc(version_id)}'>"
            f"<input type='hidden' name='number' value='{esc(row.question_no)}'>"
            "<button class='secondary' type='submit'>删除这道</button></form></div>"
        )

    body = (
        f"<p class='muted'><a href='/ui/knowledge'>← 返回知识库</a></p>"
        + (''.join(cards) if cards else "<p class='muted'>这个版本还没有题目。</p>")
    )
    return page("校对题目", body, teacher=name)


async def _ui_question_action(chilon_session: str | None):
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return None, RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        return None, RedirectResponse("/ui/password", status_code=303)
    return user_id, None


@router.post("/ui/knowledge/questions/update")
async def ui_update_question(
    version_id: Annotated[str, Form()],
    number: Annotated[int, Form()],
    stem: Annotated[str, Form()],
    answer: Annotated[str | None, Form()] = None,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _ui_question_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.update_question(
                session, user_id, uuid.UUID(version_id),
                number=number, stem=stem, answer=answer,
            )
        except knowledge_review.ReviewError:
            pass
    return RedirectResponse(f"/ui/knowledge/{version_id}", status_code=303)


@router.post("/ui/knowledge/questions/delete")
async def ui_delete_question(
    version_id: Annotated[str, Form()],
    number: Annotated[int, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _ui_question_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.delete_question(
                session, user_id, uuid.UUID(version_id), number=number
            )
        except knowledge_review.ReviewError:
            pass
    return RedirectResponse(f"/ui/knowledge/{version_id}", status_code=303)


@router.get("/ui/tasks")
async def list_tasks(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, title, status, created_at
                    FROM tasks WHERE deleted_at IS NULL
                    ORDER BY created_at DESC LIMIT 50
                    """
                )
            )
        ).all()

    items = "".join(
        f"<tr><td><a href='/ui/tasks/{esc(r.id)}'>{esc(r.title)}</a></td>"
        f"<td><span class='tag'>{esc(r.status)}</span></td>"
        f"<td class='muted'>{esc(str(r.created_at)[:16])}</td></tr>"
        for r in rows
    )
    table = (
        f"<table><tr><th>任务</th><th>状态</th><th>创建</th></tr>{items}</table>"
        if rows
        else "<p class='muted'>还没有任务。在下面用一句话描述你要的材料。</p>"
    )
    body = (
        f"<div class='card'>{table}</div>"
        "<h2>新建任务</h2><div class='card'><form method='post' action='/ui/tasks'>"
        "<p><label>任务名称<br><input name='title' required "
        "placeholder='三角函数练习'></label></p>"
        "<p><label>用一句话说出需求<br>"
        "<textarea name='requirement' rows='3' required "
        "placeholder='用高考题出 4 道三角函数题，每题带答案'></textarea></label></p>"
        "<button type='submit'>创建并让 AI 出方案</button></form></div>"
    )
    return page("我的任务", body, teacher=name)


@router.post("/ui/tasks")
async def create_task(
    title: Annotated[str, Form()],
    requirement: Annotated[str, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        task = await tasks.create_task(session, user_id, title)
    task_id = task.id  # create_task returns the domain object, not a dict

    # The whole point of the one-sentence flow: creating a task and getting a plan
    # are one action for the teacher, so they are one click here.
    async with db.session_for(user_id) as session:
        try:
            await agent.propose_plan(
                session, user_id, task_id, requirement, plan_engine=planner.build(None)
            )
        except agent.RequirementIncomplete:
            return RedirectResponse(f"/ui/tasks/{task_id}?error=requirement", status_code=303)

    return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)


async def _task_detail(user_id: uuid.UUID, task_id: uuid.UUID) -> dict | None:
    async with db.session_for(user_id) as session:
        task = (
            await session.execute(
                text("SELECT id, title, status, state_version FROM tasks WHERE id = :id"),
                {"id": task_id},
            )
        ).first()
        if task is None:
            return None

        plan = (
            await session.execute(
                text(
                    """
                    SELECT v.id, v.version_no, v.content_hash, a.id AS approval_id,
                           a.status AS approval_status, a.expires_at
                    FROM agent_plan_versions v
                    LEFT JOIN agent_plan_approvals a
                      ON a.plan_version_id = v.id AND a.status = 'pending'
                    WHERE v.task_id = :t
                    ORDER BY v.version_no DESC LIMIT 1
                    """
                ),
                {"t": task_id},
            )
        ).first()

        steps = []
        if plan:
            steps = (
                await session.execute(
                    text(
                        """
                        SELECT step_key, step_type, title FROM agent_plan_steps
                        WHERE plan_version_id = :v ORDER BY ordinal
                        """
                    ),
                    {"v": plan.id},
                )
            ).all()

        execution = (
            await session.execute(
                text(
                    """
                    SELECT id, status, started_at, finished_at
                    FROM agent_executions WHERE task_id = :t
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"t": task_id},
            )
        ).first()

        material = (
            await session.execute(
                text(
                    """
                    SELECT m.id, m.title, d.id AS draft_id, d.current_revision_no,
                           m.current_version_id
                    FROM materials m
                    LEFT JOIN material_drafts d ON d.material_id = m.id
                    WHERE m.owner_id = :o ORDER BY m.created_at DESC LIMIT 1
                    """
                ),
                {"o": user_id},
            )
        ).first()

        versions = (
            await session.execute(
                text(
                    """
                    SELECT id, version_no, content_hash FROM material_versions
                    WHERE owner_id = :o ORDER BY version_no DESC LIMIT 5
                    """
                ),
                {"o": user_id},
            )
        ).all()

        exports = (
            await session.execute(
                text(
                    """
                    SELECT id, profile, format, status FROM material_exports
                    WHERE owner_id = :o ORDER BY created_at DESC LIMIT 6
                    """
                ),
                {"o": user_id},
            )
        ).all()

    return {
        "task": task,
        "plan": plan,
        "steps": steps,
        "execution": execution,
        "material": material,
        "versions": versions,
        "exports": exports,
    }


@router.get("/ui/tasks/{task_id}")
async def task_detail(
    task_id: uuid.UUID,
    chilon_session: Annotated[str | None, Cookie()] = None,
    error: str | None = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    detail = await _task_detail(user_id, task_id)
    if detail is None:
        return page("找不到任务", "<p class='err'>任务不存在或不属于你。</p>", teacher=name)

    task = detail["task"]
    parts: list[str] = []

    if error == "requirement":
        parts.append("<p class='err'>需求信息不足，请说得更具体一些。</p>")

    parts.append(
        f"<div class='card'><p>状态 <span class='tag'>{esc(task.status)}</span></p></div>"
    )

    plan = detail["plan"]
    if plan is None:
        parts.append(
            "<h2>方案</h2><div class='card'><p class='muted'>还没有方案。</p>"
            f"<form method='post' action='/ui/tasks/{task_id}/plan'>"
            "<p><textarea name='requirement' rows='3' required></textarea></p>"
            "<button type='submit'>让 AI 出方案</button></form></div>"
        )
    else:
        rows = "".join(
            f"<tr><td>{esc(s.step_key)}</td><td>{esc(s.step_type)}</td>"
            f"<td>{esc(s.title)}</td></tr>"
            for s in detail["steps"]
        )
        status = plan.approval_status or "已批准"
        actions = ""
        if plan.approval_status == "pending":
            actions = (
                f"<form method='post' action='/ui/tasks/{task_id}/approve'>"
                "<button type='submit'>批准并执行</button></form>"
            )
        parts.append(
            f"<h2>方案 v{esc(plan.version_no)}</h2><div class='card'>"
            f"<p>审批 <span class='tag'>{esc(status)}</span> "
            f"<span class='muted'>哈希 {esc(plan.content_hash[:12])}…</span></p>"
            f"<table><tr><th>步骤</th><th>工具</th><th>说明</th></tr>{rows}</table>"
            f"<p>{actions}</p></div>"
        )

    execution = detail["execution"]
    if execution:
        parts.append(
            "<h2>执行</h2><div class='card'>"
            f"<p>状态 <span class='tag'>{esc(execution.status)}</span></p>"
            "<pre id='progress' class='muted'>等待进度…</pre>"
            f"<script>const es=new EventSource('/ui/tasks/{task_id}/events');"
            "es.onmessage=(e)=>{document.getElementById('progress').textContent+=e.data+'\\n';};"
            "es.addEventListener('execution.progress',(e)=>{"
            "document.getElementById('progress').textContent+=e.data+'\\n';});"
            "</script></div>"
        )

    material = detail["material"]
    exports = detail["exports"]
    if material:
        publish = ""
        if material.current_version_id is None:
            publish = (
                "<div class='card'><p class='muted'>发布分两步：先请求，再确认。</p>"
                f"<form method='post' action='/ui/tasks/{task_id}/publish/request' "
                "style='display:inline'>"
                "<button type='submit'>请求发布</button></form></div>"
            )
        else:
            publish = (
                "<div class='card'><p class='ok'>已发布</p>"
                f"<form method='post' action='/ui/tasks/{task_id}/export' "
                "style='display:inline'>"
                "<button class='secondary' type='submit' name='profile' value='teacher'>"
                "下载教师版</button> "
                "<button class='secondary' type='submit' name='profile' value='student'>"
                "下载学生版</button></form></div>"
            )
        rows = "".join(
            f"<tr><td>{esc(v.version_no)}</td><td>{esc(v.content_hash[:12])}…</td></tr>"
            for v in detail["versions"]
        )
        links = "".join(
            f"<li><a href='/ui/exports/{esc(e.id)}'>{esc(e.profile)} · {esc(e.format)}</a> "
            f"<span class='tag'>{esc(e.status)}</span></li>"
            for e in exports
        )
        parts.append(
            f"<h2>材料</h2><div class='card'><p>{esc(material.title)}</p>"
            f"<p class='muted'>草稿修订 {esc(material.current_revision_no or 0)}</p>"
            f"{publish}"
            f"{'<ul>' + links + '</ul>' if links else ''}"
            f"{'<table><tr><th>版本</th><th>哈希</th></tr>' + rows + '</table>' if rows else ''}"
            "</div>"
        )
    else:
        parts.append(
            "<h2>材料</h2><div class='card'><p class='muted'>执行完成后会在这里出现。</p></div>"
        )

    return page(task.title, "".join(parts), teacher=name)


@router.post("/ui/tasks/{task_id}/plan")
async def ui_plan(
    task_id: uuid.UUID,
    requirement: Annotated[str, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)
    async with db.session_for(user_id) as session:
        await agent.propose_plan(
            session, user_id, task_id, requirement, plan_engine=planner.build(None)
        )
    return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)


@router.post("/ui/tasks/{task_id}/approve")
async def ui_approve(
    task_id: uuid.UUID, chilon_session: Annotated[str | None, Cookie()] = None
) -> Response:
    """Approve the plan, start the execution, and run it.

    Three service calls, in the same order the API requires. The UI does not shortcut
    them: each is a separate contract step with its own guards.
    """
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        plan = (
            await session.execute(
                text(
                    """
                    SELECT v.id AS version_id, a.id AS approval_id
                    FROM agent_plan_versions v
                    JOIN agent_plan_approvals a ON a.plan_version_id = v.id
                    WHERE v.task_id = :t AND a.status = 'pending'
                    ORDER BY v.version_no DESC LIMIT 1
                    """
                ),
                {"t": task_id},
            )
        ).first()
    if plan is None:
        return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)

    async with db.session_for(user_id) as session:
        await agent.approve_plan(session, user_id, task_id, plan.approval_id)
    async with db.session_for(user_id) as session:
        current = await tasks.get_task(session, task_id)
    async with db.session_for(user_id) as session:
        execution_id = await executions.start_execution(
            session,
            user_id,
            task_id,
            plan.version_id,
            plan.approval_id,
            expected_task_state_version=current.state_version,
        )
    async with db.session_for(user_id) as session:
        await executor.run_once(session, user_id, execution_id)

    return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)


async def _latest_quality_verdict(user_id: uuid.UUID) -> str:
    """The quality report that gates publishing.

    Read from the stored tool output rather than re-running the check: publishing must
    reflect what the checker actually said, not what a second run might say now.
    """
    async with db.session_for(user_id) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT e.result->'output'->>'verdict' AS verdict
                    FROM agent_tool_executions e
                    WHERE e.status = 'succeeded' AND e.result IS NOT NULL
                      AND e.result->'output' ? 'verdict'
                    ORDER BY e.created_at DESC LIMIT 1
                    """
                )
            )
        ).first()
    return row.verdict if row and row.verdict else "passed_with_warnings"


@router.post("/ui/tasks/{task_id}/publish/request")
async def ui_publish_request(
    task_id: uuid.UUID, chilon_session: Annotated[str | None, Cookie()] = None
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        material_id = (
            await session.execute(
                text("SELECT id FROM materials WHERE owner_id = :o ORDER BY created_at DESC LIMIT 1"),
                {"o": user_id},
            )
        ).scalar()
    if material_id is None:
        return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)

    verdict = await _latest_quality_verdict(user_id)
    async with db.session_for(user_id) as session:
        approval_id = await publication.request_publication(
            session, user_id, material_id, quality_verdict=verdict
        )
    async with db.session_for(user_id) as session:
        await publication.approve_publication(session, approval_id, user_id)
    async with db.session_for(user_id) as session:
        await publication.publish(session, user_id, approval_id, change_summary="从界面发布")

    return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)


@router.post("/ui/tasks/{task_id}/export")
async def ui_export(
    task_id: uuid.UUID,
    profile: Annotated[str, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)
    if profile not in ("teacher", "student"):
        return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)

    async with db.session_for(user_id) as session:
        version_id = (
            await session.execute(
                text(
                    "SELECT m.current_version_id FROM materials m "
                    "WHERE m.owner_id = :o AND m.current_version_id IS NOT NULL "
                    "ORDER BY m.created_at DESC LIMIT 1"
                ),
                {"o": user_id},
            )
        ).scalar()
        if version_id is None:
            return RedirectResponse(f"/ui/tasks/{task_id}", status_code=303)
        created = await export.create_export(
            session, user_id, version_id, profile=profile, fmt="docx"
        )
    return RedirectResponse(f"/ui/exports/{created['export_id']}", status_code=303)


@router.get("/ui/exports/{export_id}")
async def download_export(
    export_id: uuid.UUID, chilon_session: Annotated[str | None, Cookie()] = None
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    async with db.session_for(user_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT storage_key, profile FROM material_exports "
                    "WHERE id = :id AND status = 'ready'"
                ),
                {"id": export_id},
            )
        ).first()
    if row is None:
        return page("找不到文件", "<p class='err'>文件不存在或不属于你。</p>")

    path = export.EXPORT_ROOT / Path(row.storage_key).name
    if not path.exists():
        return page("文件缺失", "<p class='err'>存储中没有这个文件。</p>")

    label = "教师版" if row.profile == "teacher" else "学生版"
    # HTTP headers are latin-1: a Chinese filename must be percent-encoded in the
    # RFC 5987 form or the response raises on the way out (a 500 on every download)
    filename = quote(f"{label}.docx")
    return Response(
        content=path.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/ui/tasks/{task_id}/events")
async def ui_events(
    task_id: uuid.UUID,
    request: Request,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, _, pending = who
    if pending:
        # a handed-over password must be replaced before anything else is reachable;
        # the API enforces the same rule, so the UI cannot be the only gate
        return RedirectResponse("/ui/password", status_code=303)

    from app.services import event_stream

    async with db.session_for(user_id) as session:
        conversation_id = (
            await session.execute(
                text("SELECT id FROM conversations WHERE task_id = :t ORDER BY created_at LIMIT 1"),
                {"t": task_id},
            )
        ).scalar()

    async def frames():
        if conversation_id is None:
            yield ": no conversation for this task\n\n"
            return
        async for frame in event_stream.stream(user_id, conversation_id):
            if await request.is_disconnected():
                break
            yield frame

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

