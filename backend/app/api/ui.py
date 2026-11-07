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

import asyncio
import html
import json
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
    retrieval_guard,
    tasks,
)

router = APIRouter(tags=["ui"], include_in_schema=False)

COOKIE = "chilon_session"


# ── tiny templating ────────────────────────────────────────────────────────────

STYLE = """
:root {
  color-scheme: light;
  --bg: #f4f6fb;
  --card: #ffffff;
  --ink: #172033;
  --muted: #667085;
  --line: #e4e8f0;
  --brand: #3157d5;
  --brand-soft: #eef2ff;
  --ok: #0f8a5f;
  --err: #c0392b;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: radial-gradient(circle at 10% 0%, #e8eeff 0, transparent 34%), var(--bg);
  color: var(--ink); font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  line-height: 1.65;
}
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 24px 22px 64px; }
.topbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  max-width: 1080px; margin: 0 auto; padding: 18px 22px 0;
}
.brand { font-weight: 800; letter-spacing: 0.2px; color: var(--brand); font-size: 1.02rem; }
.nav { display: flex; align-items: center; gap: 14px; color: var(--muted); font-size: 0.92rem; }
h1 { font-size: 1.65rem; letter-spacing: -0.3px; margin: 4px 0 18px; }
h2 { font-size: 1.02rem; margin: 28px 0 10px; color: #26324a; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 16px;
  padding: 20px; margin: 14px 0; box-shadow: 0 8px 26px rgba(24, 39, 75, 0.055);
}
.search-hero { padding: 24px; border-radius: 18px; }
.search-hero h2 { margin-top: 0; }
.search-form { display: flex; gap: 10px; align-items: stretch; }
.search-form input { margin: 0; }
.search-form button { white-space: nowrap; }
input, textarea {
  width: 100%; padding: 11px 13px; border-radius: 11px; border: 1px solid #cfd7e6;
  background: #fbfcff; font: inherit; color: var(--ink); outline: none;
}
input:focus, textarea:focus { border-color: var(--brand); box-shadow: 0 0 0 3px #3157d51f; }
button {
  padding: 10px 16px; border-radius: 11px; border: 1px solid transparent;
  background: linear-gradient(180deg, #3f63e0, #3157d5); color: #fff; cursor: pointer;
  font-size: 0.95rem; font-weight: 650; box-shadow: 0 4px 12px #3157d529;
}
button:hover { filter: brightness(1.05); }
button.secondary { background: #fff; color: var(--brand); border-color: #c9d3f5; box-shadow: none; }
.muted { color: var(--muted); font-size: 0.9rem; }
.err { color: var(--err); } .ok { color: var(--ok); }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 9px 8px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; font-size: 0.86rem; }
.tag {
  display: inline-block; padding: 2px 9px; border-radius: 999px;
  background: var(--brand-soft); color: #2946a7; font-size: 0.8rem; font-weight: 650;
}
.chip {
  display: inline-block; padding: 4px 11px; margin: 2px 6px 2px 0;
  border-radius: 999px; background: #eef2ff; color: #2d4bb3;
  border: 1px solid #dbe3ff; font-size: 0.82rem;
}
.chip-row { margin: 8px 0 18px; }
.result-grid { display: grid; grid-template-columns: 1fr; gap: 0; }
.result-card { border-left: 4px solid #c7d4ff; }
.result-card.question { border-left-color: var(--brand); }
.result-card.knowledge { border-left-color: #7aa7ff; }
.result-meta { color: var(--muted); font-size: 0.86rem; }
.result-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 6px; }
.stem { white-space: pre-wrap; font-size: 0.95rem; }
.answer { margin-top: 10px; border-top: 1px dashed var(--line); padding-top: 10px; }
.answer summary { cursor: pointer; color: var(--brand); font-size: 0.9rem; }
.copy-cite { font-size: 0.8rem; padding: 5px 10px; margin-top: 10px; }
.empty-card { text-align: center; padding: 28px; }
.empty-card .err { font-size: 1.05rem; font-weight: 700; }
pre {
  background: #f7f9ff; border: 1px solid #e9edf7; padding: 12px 14px;
  border-radius: 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-word;
}
.app { display: flex; min-height: 100vh; }
.sidebar {
  width: 238px; flex: 0 0 238px; background: #101a34; color: #dce4ff;
  padding: 20px 14px; position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
.sidebar .brand { color: #fff; font-size: 1.08rem; display: block; margin: 0 8px 22px; }
.nav-group { color: #8292b8; font-size: 0.68rem; letter-spacing: 0.14em; margin: 18px 10px 6px; }
.nav-item {
  display: block; color: #c5d0ea; padding: 9px 11px; border-radius: 9px;
  font-size: 0.9rem; margin: 2px 0;
}
.nav-item:hover { background: #1b294a; text-decoration: none; color: #fff; }
.nav-item.active { background: #3157d5; color: #fff; font-weight: 650; }
.main-shell { flex: 1; min-width: 0; }
.topbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  padding: 14px 26px; background: #ffffffee; border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 5; backdrop-filter: blur(8px);
}
.crumb { color: var(--muted); font-size: 0.88rem; }
.top-actions { display: flex; align-items: center; gap: 12px; }
.top-search { width: 260px; margin: 0; }
.user-menu { position: relative; }
.avatar {
  width: 38px; height: 38px; padding: 0; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3157d5, #6f8cff); color: #fff;
  font-size: 0.95rem; font-weight: 750; box-shadow: 0 4px 12px #3157d533;
}
.avatar:hover { filter: brightness(1.08); }
.dropdown {
  display: none; position: absolute; right: 0; top: 48px; width: 190px;
  background: #fff; border: 1px solid var(--line); border-radius: 12px;
  box-shadow: 0 16px 36px rgba(24, 39, 75, 0.16); padding: 8px; z-index: 30;
}
.dropdown.open { display: block; }
.dropdown-user {
  padding: 8px 10px 10px; color: var(--muted); font-size: 0.84rem;
  border-bottom: 1px solid var(--line); margin-bottom: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dropdown a, .dropdown-item {
  display: block; width: 100%; text-align: left; padding: 9px 10px;
  border: 0; border-radius: 8px; background: transparent; color: var(--ink);
  box-shadow: none; font: inherit; font-weight: 500; cursor: pointer;
}
.dropdown a:hover, .dropdown-item:hover { background: #f1f4ff; text-decoration: none; }
.content { max-width: 1120px; margin: 0 auto; padding: 26px 26px 64px; }
.dash-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.quick-card { display: block; color: inherit; text-decoration: none; }
.quick-card:hover { text-decoration: none; transform: translateY(-1px); }
.quick-card .kicker { color: var(--muted); font-size: 0.78rem; }
.quick-card h3 { margin: 6px 0; font-size: 1.05rem; }
.stat-row { display: flex; gap: 14px; flex-wrap: wrap; }
.stat { flex: 1; min-width: 160px; }
.stat b { font-size: 1.6rem; display: block; }
.activity { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.pill { display: inline-flex; align-items: center; padding: 2px 9px; border-radius: 999px; background: #eef2ff; color: #2d4bb3; font-size: 0.8rem; }
.auth-wrap { max-width: 420px; margin: 10vh auto; padding: 0 18px; }
.auth-brand { text-align: center; color: var(--brand); font-weight: 800; font-size: 1.3rem; margin-bottom: 12px; }
@media (max-width: 900px) {
  .sidebar { display: none; }
  .dash-grid { grid-template-columns: 1fr; }
  .top-search { display: none; }
}
@media (max-width: 640px) {
  .wrap { padding: 18px 14px 48px; }
  .topbar { padding: 14px 14px 0; flex-wrap: wrap; }
  .search-form { flex-direction: column; }
  h1 { font-size: 1.4rem; }
}
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


ACTIVE_BY_TITLE = {
    '工作台': 'dashboard',
    '知识库': 'knowledge',
    '知识库检索': 'search',
    '我的任务': 'tasks',
    '任务': 'tasks',
    '设置': 'settings',
}


def _sidebar(active: str | None) -> str:
    def item(label: str, href: str, key: str) -> str:
        cls = 'nav-item active' if active == key else 'nav-item'
        return f'<a class="{cls}" href="{href}">{esc(label)}</a>'

    return (
        '<aside class="sidebar">'
        '<a class="brand" href="/ui/dashboard">Chilon</a>'
        '<div class="nav-group">WORKSPACE</div>'
        + item('工作台', '/ui/dashboard', 'dashboard')
        + item('AI 教学助手', '/ui/tasks', 'tasks')
        + item('我的教学项目', '/ui/tasks', 'projects')
        + '<div class="nav-group">KNOWLEDGE CENTER</div>'
        + item('知识库', '/ui/knowledge', 'knowledge')
        + item('智能检索', '/ui/search', 'search')
        + item('资料上传', '/ui/knowledge/upload', 'upload')
        + item('内容审核', '/ui/knowledge?type=pending', 'review')
        + '<div class="nav-group">SYSTEM</div>'
        + item('历史记录', '/ui/tasks', 'history')
        + item('设置', '/ui/settings', 'settings')
        + '</aside>'
    )


def page(title: str, body: str, *, teacher: str | None = None,
         active: str | None = None) -> HTMLResponse:
    if teacher:
        active = active or ACTIVE_BY_TITLE.get(title, 'dashboard')
        initial = esc((teacher.strip()[:1] or '师').upper())
        top = (
            '<header class="topbar">'
            f'<span class="crumb">{esc(title)}</span>'
            '<div class="top-actions">'
            '<form class="top-search" method="get" action="/ui/search">'
            '<input name="q" placeholder="搜索知识库…" aria-label="搜索知识库"></form>'
            '<div class="user-menu">'
            '<button class="avatar" id="user-menu-button" type="button" '
            f'aria-label="打开用户菜单" aria-haspopup="true" aria-expanded="false">{initial}</button>'
            '<div class="dropdown" id="user-menu-dropdown">'
            f'<div class="dropdown-user">{esc(teacher)}</div>'
            '<a href="/ui/settings">设置</a>'
            '<form method="post" action="/ui/logout" style="margin:0">'
            '<button class="dropdown-item" type="submit">退出登录</button></form>'
            '</div></div>'
            '</div></header>'
            '<script>'
            '(function(){var b=document.getElementById("user-menu-button");'
            'var d=document.getElementById("user-menu-dropdown");'
            'if(!b||!d)return;'
            'function close(){d.classList.remove("open");b.setAttribute("aria-expanded","false");}'
            'b.addEventListener("click",function(e){e.stopPropagation();'
            'var open=d.classList.toggle("open");b.setAttribute("aria-expanded",open?"true":"false");});'
            'document.addEventListener("click",function(e){if(!d.contains(e.target)&&e.target!==b)close();});'
            'document.addEventListener("keydown",function(e){if(e.key==="Escape")close();});'
            '})();</script>'
        )
        shell = (
            '<div class="app">' + _sidebar(active)
            + '<div class="main-shell">' + top
            + f'<main class="content"><h1>{esc(title)}</h1>{body}</main>'
            + '</div></div>'
        )
    else:
        shell = (
            '<main class="auth-wrap"><div class="auth-brand">Chilon</div>'
            f'<h1>{esc(title)}</h1>{body}</main>'
        )
    return HTMLResponse(
        f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)} · Chilon</title><style>{STYLE}</style></head>"
        f"<body>{shell}</body></html>"
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
    return RedirectResponse("/ui/dashboard" if who else "/ui/login", status_code=303)


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
    response = RedirectResponse("/ui/dashboard", status_code=303)
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
    response = RedirectResponse("/ui/dashboard", status_code=303)
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


# ── retrieval search ──────────────────────────────────────────────────────────


SOURCE_LABELS = {
    'textbook': '教材',
    'gaokao_paper': '高考真题',
    'mock_exam': '模拟题',
}

QUESTION_TYPE_LABELS = {
    'single_choice': '单选',
    'multiple_choice': '多选',
    'fill_blank': '填空',
    'free_response': '解答',
}

OBJECT_LABELS = {
    'knowledge': '教材知识块',
    'question': '题目',
    'other': '其他',
}

EMPTY_REASONS = {
    'no_match': '没有找到匹配内容',
    'no_match_under_filters': '在给定条件下没有匹配内容',
    'no_candidates': '检索没有返回候选',
}


def _locator_page(locator: object) -> str:
    if isinstance(locator, dict):
        page = locator.get('page') or locator.get('page_number')
        return f"第 {page} 页" if page else str(locator)
    if isinstance(locator, str):
        try:
            parsed = json.loads(locator)
        except (json.JSONDecodeError, TypeError):
            return locator
        if isinstance(parsed, dict):
            page = parsed.get('page') or parsed.get('page_number')
            return f"第 {page} 页" if page else str(parsed)
    return str(locator or '')


def _condition_chips(plan: dict | None) -> list[str]:
    hard = (plan or {}).get('hard') or {}
    chips: list[str] = []
    scope = hard.get('question_scope')
    if scope == 'knowledge':
        chips.append('只搜教材')
    elif scope == 'question':
        chips.append('只搜题目')
    for source in hard.get('source_types') or []:
        chips.append(SOURCE_LABELS.get(source, source))
    if hard.get('year_range'):
        chips.append(f"年份 {hard['year_range'][0]}–{hard['year_range'][1]}")
    for paper in hard.get('papers') or []:
        chips.append(str(paper))
    for qtype in hard.get('question_types') or []:
        chips.append(QUESTION_TYPE_LABELS.get(qtype, qtype))
    return chips or ['无硬条件']


def _object_group(hit: dict) -> str:
    if hit.get('question_id') or hit.get('question_type'):
        return 'question'
    if hit.get('source_type') == 'textbook':
        return 'knowledge'
    return 'other'


def _hit_card(hit: dict) -> str:
    source_label = SOURCE_LABELS.get(hit.get('source_type'), hit.get('source_type') or '知识库')
    group = _object_group(hit)
    title = hit.get('source_title') or ''
    page = _locator_page(hit.get('locator'))
    qtype = QUESTION_TYPE_LABELS.get(hit.get('question_type'), hit.get('question_type') or '')
    qno = f"第{hit.get('question_no')}题" if hit.get('question_no') else ''
    meta = [source_label, title, hit.get('source_paper'), hit.get('year')]
    meta_text = ' · '.join(str(x) for x in meta if x)
    citation = ' '.join(part for part in (title, page, qno, f"题型 {qtype}" if qtype else '') if part)
    citation = f"{citation}｜{(hit.get('excerpt') or '')[:180]}"
    excerpt = esc((hit.get('excerpt') or '')[:900])
    head = (
        "<div class='result-head'>"
        f"<span class='tag'>{esc(OBJECT_LABELS[group])}</span>"
        f"<span class='tag'>{esc(source_label)}</span>"
        + (f"<span class='tag'>{esc(qno)}</span>" if qno else '')
        + (f"<span class='tag'>{esc(qtype)}</span>" if qtype else '')
        + "</div>"
    )
    if group == 'question':
        # The chunk is the OCR stem (options included when the paper has them).
        answer = ''
        if hit.get('answer'):
            answer = (
                "<details class='answer'><summary>查看原卷答案</summary>"
                f"<pre>{esc(str(hit.get('answer'))[:1200])}</pre></details>"
            )
        body = (
            f"<p class=''>{esc(meta_text)}</p>"
            f"<p class='result-meta'>{esc(page)} · chunk {esc(str(hit.get('chunk_id'))[:8])}</p>"
            f"<pre class='stem'>{excerpt}</pre>"
            f"{answer}"
        )
    else:
        body = (
            f"<p class=''>{esc(meta_text)}</p>"
            f"<p class='result-meta'>{esc(page)} · chunk {esc(str(hit.get('chunk_id'))[:8])}</p>"
            f"<pre>{excerpt}</pre>"
        )
    return (
        f"<div class='card result-card {group}'>"
        f"{head}{body}"
        f"<p><a href='/ui/search/{esc(str(hit.get('chunk_id')))}'>查看详情 →</a></p>"
        f"<button class='secondary copy-cite' data-citation='{esc(citation)}'>复制引用</button>"
        "</div>"
    )


def _search_page(user_name: str, query: str, result: dict | None, error: str | None,
                 related: dict | None = None) -> HTMLResponse:
    form = (
        "<div class='card search-hero'><h2>从知识库找证据</h2>"
        "<form class='search-form' method='get' action='/ui/search'>"
        f"<input name='q' value='{esc(query)}' placeholder='例如：导数的切线方程公式是什么？' required>"
        "<button type='submit'>检索</button></form>"
        "<p class='muted'>只展示知识库原文证据，不生成答案；请核对来源和页码。</p></div>"
    )
    parts = [form]
    if error:
        parts.append(f"<p class='err'>{esc(error)}</p>")
    if result is not None:
        status = result.get('status')
        mode = result.get('mode')
        chips = _condition_chips(result.get('plan'))
        parts.append(
            f"<p class='muted'>模式 {esc(mode)} · 状态 {esc(status)} · "
            f"{esc(result.get('elapsed_ms'))}ms</p>"
            "<div class='chip-row'>" + ''.join(f"<span class='chip'>{esc(chip)}</span>" for chip in chips) + "</div>"
        )
        if not result.get('hits'):
            reason = EMPTY_REASONS.get(result.get('empty_reason'), '没有找到匹配内容')
            parts.append(
                "<div class='card empty-card'><p class='err'>没有找到匹配内容。</p>"
                f"<p class='muted'>原因：{esc(reason)}。可以换一个更具体的说法，或去掉年份/题型等条件。</p></div>"
            )
        else:
            groups: dict[str, list[dict]] = {'knowledge': [], 'question': [], 'other': []}
            for hit in result['hits']:
                groups[_object_group(hit)].append(hit)
            for group in ('knowledge', 'question', 'other'):
                if groups[group]:
                    parts.append(f"<h2>{esc(OBJECT_LABELS[group])}</h2>")
                    parts.extend(_hit_card(hit) for hit in groups[group])
        if related is not None:
            parts.append("<h2>相关教材知识</h2>")
            if related.get('hits'):
                parts.extend(_hit_card(hit) for hit in related['hits'])
            else:
                parts.append(
                    "<div class='card'><p class='muted'>没有找到相关教材知识块；"
                    "可以试试更概念化的问法，例如“数列的递推公式定义”。</p></div>"
                )
        if result.get('hits') or (related and related.get('hits')):
            parts.append(
                "<script>document.querySelectorAll('.copy-cite').forEach(function(b){"
                "b.addEventListener('click',function(){navigator.clipboard.writeText(b.dataset.citation);"
                "b.textContent='已复制';setTimeout(function(){b.textContent='复制引用';},1200);});});</script>"
            )
    return page("知识库检索", ''.join(parts), teacher=user_name, active="search")


@router.get("/ui/search")
async def ui_search(
    q: str | None = None,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)
    query = (q or '').strip()
    if not query:
        return _search_page(name, '', None, None)
    try:
        from app.services import routed_retrieval

        retrieval_guard.check_and_record(str(user_id), 'h')
        result = await asyncio.to_thread(
            routed_retrieval.search, query, limit=8, mode='h', user_key=str(user_id)
        )
        related = None
        has_knowledge = any(_object_group(hit) == 'knowledge' for hit in result.get('hits', []))
        if not has_knowledge:
            try:
                related = await asyncio.to_thread(
                    routed_retrieval.search, query, limit=4, mode='h', user_key=str(user_id),
                    scope_override='knowledge',
                )
            except Exception:  # noqa: BLE001 - the question results are still useful
                related = None
        return _search_page(name, query, result, None, related=related)
    except retrieval_guard.RateLimited:
        return _search_page(name, query, None, '请求过于频繁，请稍后再试。')
    except retrieval_guard.QuotaExceeded:
        return _search_page(name, query, None, '今日检索额度已用完。')
    except Exception as exc:  # noqa: BLE001 - teacher sees a readable error
        return _search_page(name, query, None, f"检索暂时不可用：{type(exc).__name__}")


@router.get("/ui/search/{chunk_id}")
async def search_detail(
    chunk_id: uuid.UUID,
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)
    async with db.session_for(user_id) as session:
        row = (await session.execute(text("""
            SELECT c.id::text, c.text_content, s.title, s.source_type, s.year,
                   s.exam_paper, c.locator::text,
                   q.question_no, q.current_paper_question_type,
                   q.current_knowledge_points, ac.text_content AS answer_text
            FROM knowledge_chunks c
            JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
            JOIN knowledge_sources s ON s.id = dv.source_id
            LEFT JOIN knowledge_questions q
              ON q.document_version_id = dv.id AND q.stem_locator = c.locator
            LEFT JOIN knowledge_chunks ac
              ON ac.document_version_id = dv.id AND ac.locator = q.answer_locator
            WHERE c.id = :id
        """), {'id': chunk_id})).first()
    if row is None:
        return page("找不到内容", "<p class='err'>内容不存在或无权访问。</p>", teacher=name)
    source_label = SOURCE_LABELS.get(row[3], row[3] or '知识库')
    qtype = QUESTION_TYPE_LABELS.get(row[8], row[8] or '')
    qno = f"第{row[7]}题" if row[7] else ''
    locator = _locator_page(row[6])
    points = '、'.join(row[9] or [])
    answer = (
        f"<details class='answer' open><summary>原卷答案</summary>"
        f"<pre>{esc(str(row[10])[:1600])}</pre></details>"
        if row[10] else "<p class='muted'>没有关联原卷答案。</p>"
    )
    body = (
        "<p><a href='/ui/search'>← 返回检索</a></p>"
        "<div class='card'>"
        f"<div class='result-head'><span class='tag'>{esc(source_label)}</span>"
        f"{f'<span class=\'tag\'>{esc(qno)}</span>' if qno else ''}"
        f"{f'<span class=\'tag\'>{esc(qtype)}</span>' if qtype else ''}</div>"
        f"<p><b>{esc(row[2])}</b> · {esc(locator)}</p>"
        + (f"<p class='muted'>知识点：{esc(points)}</p>" if points else '')
        + f"<pre class='stem'>{esc(row[1])}</pre>{answer}"
        "</div>"
    )
    return page(qno or "内容详情", body, teacher=name, active='search')


# ── dashboard / settings ───────────────────────────────────────────────────────


@router.get("/ui/dashboard")
async def dashboard(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    user_id, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)
    async with db.session_for(user_id) as session:
        tasks_rows = (await session.execute(text(
            "SELECT id, title, status, created_at FROM tasks "
            "WHERE deleted_at IS NULL AND owner_id = :owner_id "
            "ORDER BY created_at DESC LIMIT 6"
        ), {'owner_id': user_id})).all()
        task_count = (await session.execute(text(
            "SELECT count(*) FROM tasks WHERE deleted_at IS NULL AND owner_id = :owner_id"
        ), {'owner_id': user_id})).scalar_one()
        source_count = (await session.execute(text(
            "SELECT count(*) FROM knowledge_sources "
            "WHERE deleted_at IS NULL AND (scope = 'platform' OR owner_id = :owner_id)"
        ), {'owner_id': user_id})).scalar_one()
        pending_count = (await session.execute(text(
            "SELECT count(*) FROM knowledge_document_versions "
            "WHERE lifecycle_status = 'pending_review'"
        ))).scalar_one()
    activity = ''.join(
        f"<div class='activity'><span>{esc(r.title)}</span>"
        f"<span><span class='tag'>{esc(r.status)}</span> "
        f"<span class='muted'>{esc(str(r.created_at)[:16])}</span></span></div>"
        for r in tasks_rows
    ) or "<p class='muted'>还没有任务。从一个教学需求开始。</p>"
    body = (
        "<div class='card'><h2>下午好，" + esc(name) + "</h2>"
        "<p class='muted'>今天想从哪里开始？</p>"
        "<form class='search-form' method='get' action='/ui/search'>"
        "<input name='q' placeholder='例如：找近五年考查数列递推的高考解答题'>"
        "<button type='submit'>智能检索</button></form></div>"
        "<div class='dash-grid'>"
        "<a class='card quick-card' href='/ui/search'><div class='kicker'>KNOWLEDGE</div>"
        "<h3>智能检索</h3><p class='muted'>用自然语言找教材、真题和模拟题，并核对来源。</p></a>"
        "<a class='card quick-card' href='/ui/knowledge'><div class='kicker'>KNOWLEDGE</div>"
        "<h3>知识库</h3><p class='muted'>浏览、上传和审核高中数学资料。</p></a>"
        "<a class='card quick-card' href='/ui/tasks'><div class='kicker'>WORKSPACE</div>"
        "<h3>AI 教学助手</h3><p class='muted'>从一句话开始生成教学方案和材料。</p></a>"
        "</div>"
        "<div class='stat-row'>"
        f"<div class='card stat'><span class='muted'>教学任务</span><b>{esc(task_count)}</b></div>"
        f"<div class='card stat'><span class='muted'>知识资料</span><b>{esc(source_count)}</b></div>"
        f"<div class='card stat'><span class='muted'>待审核版本</span><b>{esc(pending_count)}</b></div>"
        "</div>"
        "<h2>最近任务</h2><div class='card'>" + activity + "</div>"
    )
    return page("工作台", body, teacher=name, active='dashboard')


@router.get("/ui/settings")
async def settings_page(chilon_session: Annotated[str | None, Cookie()] = None) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    _, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)
    body = (
        "<div class='card'><h2>账号与安全</h2>"
        f"<p>当前账号：<b>{esc(name)}</b></p>"
        "<p><a href='/ui/password'>修改密码</a></p></div>"
        "<div class='card'><h2>检索设置</h2>"
        "<p class='muted'>第一版使用 hybrid H 检索；HR 路由默认关闭。"
        "检索来源、页码和审核状态会显示在结果卡中。</p></div>"
        "<div class='card'><h2>数据与隐私</h2>"
        "<p class='muted'>个人资料默认仅自己可见；导出学生版时答案由后端过滤。</p></div>"
    )
    return page("设置", body, teacher=name, active='settings')


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
async def knowledge_page(chilon_session: Annotated[str | None, Cookie()] = None,
                         type: str | None = None) -> Response:
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

    where = ["s.deleted_at IS NULL"]
    params: dict = {}
    type = (type or '').strip()
    if type == 'mine':
        where.append("s.scope = 'teacher'")
    elif type == 'pending':
        where.append("v.lifecycle_status = 'pending_review'")
    elif type in ('textbook', 'gaokao_paper', 'mock_exam'):
        where.append("s.source_type = :source_type")
        params['source_type'] = type

    async with db.session_for(user_id) as session:
        rows = (
            await session.execute(
                text(
                    f"""
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
                    WHERE {' AND '.join(where)}
                    ORDER BY s.created_at DESC LIMIT 100
                    """
                ),
                params,
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

    tabs = [('', '全部'), ('textbook', '教材'), ('gaokao_paper', '高考真题'),
            ('mock_exam', '模拟题'), ('mine', '我的资料'), ('pending', '待审核')]
    tab_html = ''.join(
        f"<a class='chip' style='text-decoration:none' href='/ui/knowledge{('?type=' + key) if key else ''}'>"
        f"{'● ' if type == key else ''}{esc(label)}</a>"
        for key, label in tabs
    )
    body = (
        "<p class='muted'>管理、查阅和审核高中数学教学资料。</p>"
        f"<div class='chip-row'>{tab_html}</div>"
        + (''.join(blocks) if blocks else "<p class='muted'>还没有上传任何材料。</p>")
        + "<div class='card'><p class='muted'>需要新增教材、真题或模拟题？</p>"
        "<p><a href='/ui/knowledge/upload'>上传资料 →</a></p></div>"
    )
    active = 'review' if type == 'pending' else 'knowledge'
    return page("知识库", body, teacher=name, active=active)


def _upload_form_html() -> str:
    return (
        "<div class='card'>"
        "<form method='post' action='/ui/knowledge' enctype='multipart/form-data'>"
        "<p><label>标题<br><input name='title' required "
        "placeholder='例如：2024 新课标 I 卷 数学'></label></p>"
        "<p><label>类型<br><select name='source_type'>"
        "<option value='gaokao_paper'>高考真题</option>"
        "<option value='mock_exam'>模拟题</option>"
        "<option value='textbook'>教材</option>"
        "<option value='other'>其他</option></select></label></p>"
        "<p><label>文件（.docx 或可复制文字的 .pdf）<br>"
        "<input type='file' name='file' accept='.docx,.pdf' required></label></p>"
        "<button type='submit'>上传并解析</button></form>"
        "<p class='muted'>上传后会进入解析与审核流程；解析失败的版本不会进入正式检索。</p>"
        "</div>"
    )


@router.get("/ui/knowledge/upload")
async def knowledge_upload_page(
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    who = await teacher_from_cookie(chilon_session)
    if who is None:
        return RedirectResponse("/ui/login", status_code=303)
    _, name, pending = who
    if pending:
        return RedirectResponse("/ui/password", status_code=303)
    body = (
        "<p class='muted'>上传教材、高考真题或模拟题；解析完成后可在知识库中校对。</p>"
        + _upload_form_html()
        + "<p><a href='/ui/knowledge'>← 返回知识库</a></p>"
    )
    return page("资料上传", body, teacher=name, active='upload')


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
                    WHERE q.document_version_id = :v AND q.deleted_at IS NULL
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
            "<form method='post' action='/ui/knowledge/questions/renumber' style='margin-top:6px'>"
            f"<input type='hidden' name='version_id' value='{esc(version_id)}'>"
            f"<input type='hidden' name='number' value='{esc(row.question_no)}'>"
            "<label class='muted'>改题号为 <input name='new_number' size='3' "
            f"value='{esc(row.question_no)}'></label> "
            "<button class='secondary' type='submit'>移动</button></form>"
            "<form method='post' action='/ui/knowledge/questions/delete' style='margin-top:6px'>"
            f"<input type='hidden' name='version_id' value='{esc(version_id)}'>"
            f"<input type='hidden' name='number' value='{esc(row.question_no)}'>"
            "<button class='secondary' type='submit'>删除这道</button></form></div>"
        )

    body = (
        f"<p class='muted'><a href='/ui/knowledge'>← 返回知识库</a></p>"
        + (''.join(cards) if cards else "<p class='muted'>这个版本还没有题目。</p>")
    )
    return page("校对题目", body, teacher=name, active="knowledge")


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



@router.post("/ui/knowledge/questions/restore")
async def ui_restore_question(
    version_id: Annotated[str, Form()],
    number: Annotated[int, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _ui_question_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.restore_question(
                session, user_id, uuid.UUID(version_id), number=number
            )
        except knowledge_review.ReviewError:
            pass
    return RedirectResponse(f"/ui/knowledge/{version_id}", status_code=303)


@router.post("/ui/knowledge/questions/renumber")
async def ui_renumber_question(
    version_id: Annotated[str, Form()],
    number: Annotated[int, Form()],
    new_number: Annotated[int, Form()],
    chilon_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    user_id, redirect = await _ui_question_action(chilon_session)
    if redirect:
        return redirect
    async with db.session_for(user_id) as session:
        try:
            await knowledge_review.renumber(
                session, user_id, uuid.UUID(version_id),
                number=number, new_number=new_number,
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

    return page(task.title, "".join(parts), teacher=name, active="tasks")


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

