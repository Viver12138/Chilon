#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 PostgreSQL 中的「受限资料」（模拟题 / 教材）投影为 Obsidian 内部审校笔记。

背景（V1.2 阶段 2–3，PG 是 SSOT）：
- 模拟题：67 sources / 931 chunks（每 chunk 一道题，答案/解析未入库；答案 PDF 在 corpus/mock-exams）；
- 教材：5 sources / 1797 chunks（locator page/part，无章节元数据）；
- 两者在 PG 均为 rights_status='restricted'、distribution_scope='classroom'；
- vault 的 04_Exams/MockExams、03_Textbooks 为空，本工具负责首次投影。

参数（均可用环境变量提供，便于他人复跑）：
- ``--vault``：Obsidian vault 根目录；默认读环境变量 ``CHILON_VAULT``；两者都没有时直接报错。
- ``--database-url``：PostgreSQL 连接串；默认依次读 ``CHILON_TEST_DATABASE_URL``、
  ``CHILON_DATABASE_URL``；都没有时才回退到当前本机容器 env（``chilon-pg-corpus``）。
- ``--apply`` 写库/写文件（默认 dry-run）；``--only mock|textbook`` 只投影一种；
  ``--force-generated`` 刷新本工具以前生成的文件（人工编辑过的仍跳过）。

安全约束：
- 只写 vault 内 `04_Exams/MockExams/**`、`03_Textbooks/**`、两份总览
  （`10_Indexes/模拟题总览.md`、`教材总览.md`），以及受限资料的状态行
  （首页/数据来源与许可/迁移记录中的生成段）；**从不触碰高考卡**。
- 只覆盖「带 `generated_from: postgres` 且 `human_edited: false`」的文件；人工编辑过的跳过；
  默认不覆盖已有文件（`--force-generated` 才刷新本工具生成的文件）。
- 不打印数据库密码（连接串可由环境变量/参数提供；容器回退时只从容器 env 读取、从不回显）。
- 所有生成物带 `rights_status: restricted` / `distribution_scope: classroom` / `internal_only: true`
  与正文版权段；答案是“未入库，见 PDF”，不伪造。

用法（.venv，含 psycopg）：
    $env:CHILON_VAULT = "<vault 路径>"; $env:CHILON_TEST_DATABASE_URL = "<连接串>"
    .\\.venv\\Scripts\\python.exe tools/project_restricted_corpus.py --vault <vault>   # dry-run（默认）
    ... --apply
    ... --only mock|textbook
    ... --force-generated

退出码：0 成功；2 参数/数据校验失败；3 数据库不可用；4 缺依赖。
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse

try:
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    print('缺少依赖 psycopg：请用 .venv 运行（.\\.venv\\Scripts\\python.exe）', file=sys.stderr)
    sys.exit(4)

# vault 相关路径在 main() 解析参数后由 _set_vault() 赋值（模块级全局，便于所有函数复用）。
VAULT: pathlib.Path | None = None
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'projection'
MOCK_PDF_DIR = ROOT / 'corpus' / 'mock-exams'
TB_PDF_DIR = ROOT / 'corpus' / 'textbooks'
MOCK_ROOT: pathlib.Path | None = None
TB_ROOT: pathlib.Path | None = None
MOCK_INDEX: pathlib.Path | None = None
TB_INDEX: pathlib.Path | None = None
HOME: pathlib.Path | None = None
RIGHTS: pathlib.Path | None = None
MIGRATION: pathlib.Path | None = None
TODAY = _dt.date.today().isoformat()
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'

TYPE_CN = {'single_choice': '单选', 'multiple_choice': '多选', 'fill_blank': '填空', 'free_response': '解答'}
ILLEGAL = re.compile(r'[<>:"/\\|?*#\[\]^\x00-\x1f]')
MARK_MOCK = '<!-- BEGIN generated: restricted-corpus-mock -->'
MARK_TB = '<!-- BEGIN generated: restricted-corpus-textbook -->'


# ---------------------------------------------------------------- 路径 / 连接
def _set_vault(root: pathlib.Path) -> None:
    """解析 vault 路径并更新所有模块级路径（main() 里调用）。"""
    global VAULT, MOCK_ROOT, TB_ROOT, MOCK_INDEX, TB_INDEX, HOME, RIGHTS, MIGRATION
    VAULT = root
    MOCK_ROOT = root / '04_Exams' / 'MockExams'
    TB_ROOT = root / '03_Textbooks'
    MOCK_INDEX = root / '10_Indexes' / '模拟题总览.md'
    TB_INDEX = root / '10_Indexes' / '教材总览.md'
    HOME = root / '10_Indexes' / '首页.md'
    RIGHTS = root / '10_Indexes' / '数据来源与许可.md'
    MIGRATION = root / '08_Review' / '迁移记录.md'


def _db_url(database_url: str | None = None):
    """连接串优先级：--database-url → CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL
    → 当前本机容器 env（chilon-pg-corpus）。返回 (url, 可公开的来源标签)，不打印密码。"""
    if database_url:
        return database_url, '--database-url'
    for env in ('CHILON_TEST_DATABASE_URL', 'CHILON_DATABASE_URL'):
        url = os.environ.get(env)
        if url:
            return url, f'环境变量 {env}'
    try:
        p = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError('找不到 docker 命令；请用 --database-url 或设置 CHILON_TEST_DATABASE_URL')
    pw = (p.stdout or '').strip()
    if p.returncode != 0 or not pw:
        raise RuntimeError('无法从容器 env 读取 POSTGRES_PASSWORD（容器未启动？）；'
                           '请用 --database-url 或设置 CHILON_TEST_DATABASE_URL')
    url = f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    return url, f'容器 {CONTAINER} env（{DB_HOST}:{DB_PORT}/{DB_NAME}）'


def safe_name(title: str, limit: int = 90) -> str:
    s = ILLEGAL.sub('', title)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('. ')
    if len(s) > limit:
        s = s[:limit].rstrip('. ')
    if not s:
        s = 'untitled'
    if s.upper() in {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
                     'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4',
                     'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}:
        s = f'_{s}'
    return s


def yaml_scalar(v) -> str:
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if re.fullmatch(r'[A-Za-z0-9_.\-/]+', s):
        return s
    return "'" + s.replace("'", "''") + "'"


def yaml_list_block(key: str, items) -> str:
    items = list(items or [])
    if not items:
        return f'{key}: []'
    return f'{key}:\n' + '\n'.join(f'  - {yaml_scalar(x)}' for x in items)


def frontmatter(fields: list[tuple[str, object]]) -> str:
    out = ['---']
    for key, value in fields:
        if isinstance(value, str) and '\n' in value:
            out.append(f'{key}: |')
            out.extend('  ' + line for line in value.splitlines())
        else:
            out.append(f'{key}: {yaml_scalar(value)}')
    out.append('---')
    return '\n'.join(out)


def md_body(text: str) -> str:
    """OCR/题干原文防破坏：行首 # 与分隔线加转义，其余保持原样。"""
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    fixed = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^#{1,6}\s', line) or stripped in ('---', '***', '___', '+++'):
            line = '\\' + line
        fixed.append(line.rstrip())
    return '\n'.join(fixed).strip()


def copyright_block(what: str) -> str:
    return '\n'.join([
        '## 版权与使用边界',
        '',
        '- `rights_status: restricted`　`distribution_scope: classroom`　`internal_only: true`',
        f'- 本文件由 `tools/project_restricted_corpus.py` 从 PostgreSQL 投影生成（`generated_from: postgres`），'
        f'仅用于库内审校；**不得对外分发/公开发布**。',
        f'- {what}',
        '- 人工修改本文件前，请先将 `human_edited: true` 并说明原因；本工具默认不覆盖人工编辑文件。',
    ])


def strip_generated_at(text: str) -> str:
    return '\n'.join(line for line in text.splitlines()
                     if not line.startswith(('generated_at:', 'updated:'))) + '\n'


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- PDF 匹配
def build_pdf_index():
    mock = {}
    for p in sorted(MOCK_PDF_DIR.glob('*.pdf')):
        if p.name.endswith('__数学试题.pdf'):
            stem = p.name[: -len('__数学试题.pdf')]
            ans = p.with_name(stem + '__数学答案.pdf')
            mock[stem] = {'pdf': p, 'answer': ans if ans.exists() else None}
    tb = {p.stem: p for p in sorted(TB_PDF_DIR.glob('*.pdf'))}
    return mock, tb


def match_pdf(title: str, index: dict):
    """精确优先、模糊兜底。返回 (key, mode) 或 (None, None)。"""
    if title in index:
        return title, 'exact'
    norm = lambda s: re.sub(r'\s+', '', s.replace('（', '(').replace('）', ')'))
    best, score = None, 0.0
    for key in index:
        r = difflib.SequenceMatcher(None, norm(title), norm(key)).ratio()
        if r > score:
            best, score = key, r
    if best is not None and score >= 0.88:
        return best, f'fuzzy:{score:.2f}'
    return None, None


# ---------------------------------------------------------------- PG 读取
def fetch_data(conn):
    cur = conn.cursor()

    def q(sql):
        cur.execute(sql)
        return cur.fetchall()

    mock_sources = q("""
        SELECT s.id::text, s.title, s.year, s.rights_status, s.distribution_scope,
               dv.id::text, dv.storage_key, s.created_at::text
        FROM knowledge_sources s
        JOIN knowledge_document_versions dv ON dv.source_id = s.id
        WHERE s.source_type = 'mock_exam'
        ORDER BY s.title
    """)
    mock_rows = q("""
        SELECT s.id::text, c.chunk_key, c.ordinal, c.locator, c.text_content,
               q.id::text, q.question_no, q.current_paper_question_type,
               coalesce(q.current_knowledge_points, '{}'),
               (c.locator->>'page_number')::int, (c.locator->>'question_index')::int,
               c.id::text
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        LEFT JOIN knowledge_questions q
               ON q.document_version_id = c.document_version_id AND q.stem_locator = c.locator
        WHERE s.source_type = 'mock_exam'
        ORDER BY s.title, (c.locator->>'page_number')::int,
                 (c.locator->>'question_index')::int, c.ordinal
    """)
    tb_sources = q("""
        SELECT s.id::text, s.title, s.year, s.rights_status, s.distribution_scope, dv.id::text
        FROM knowledge_sources s
        JOIN knowledge_document_versions dv ON dv.source_id = s.id
        WHERE s.source_type = 'textbook'
        ORDER BY s.title
    """)
    tb_rows = q("""
        SELECT s.id::text, c.chunk_key, c.ordinal, c.text_content,
               (c.locator->>'page')::int, (c.locator->>'part')::int, c.id::text
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'textbook'
        ORDER BY s.title, (c.locator->>'page')::int, (c.locator->>'part')::int,
                 c.ordinal, c.id
    """)
    return mock_sources, mock_rows, tb_sources, tb_rows


# ---------------------------------------------------------------- 内容生成
def build_mock(sources, rows, pdf_index, now: str):
    """返回 (files[{path,content,kind,source_id}], stats)。"""
    files, stats = [], {'sources': 0, 'cards': 0, 'pdf_exact': 0, 'pdf_fuzzy': 0, 'pdf_none': 0}
    by_source = {}
    for row in rows:
        by_source.setdefault(row[0], []).append(row)

    for sid, title, year, rights, dist, dvid, storage_key, created in sources:
        stats['sources'] += 1
        safe = safe_name(title)
        folder = MOCK_ROOT / str(year) / safe
        set_name = safe
        card_stem_base = safe
        key, mode = match_pdf(title, pdf_index)
        if mode == 'exact':
            stats['pdf_exact'] += 1
        elif mode and mode.startswith('fuzzy'):
            stats['pdf_fuzzy'] += 1
        else:
            stats['pdf_none'] += 1
        pdf = pdf_index[key]['pdf'] if key else None
        answer_pdf = pdf_index[key]['answer'] if key else None
        pdf_field = str(pdf) if pdf else str(MOCK_PDF_DIR)
        answer_field = str(answer_pdf) if answer_pdf else str(MOCK_PDF_DIR)

        items = by_source.get(sid, [])
        if not items:
            continue
        if any(r[5] is None for r in items):
            raise RuntimeError(f'{title}: 有 chunk 未匹配到 knowledge_questions（投影需要题号/题型）')
        # 卡片
        cards = []
        for (sid2, chunk_key, ordinal, locator, text, qid, qno, qtype, kps,
             page, qidx, chunk_id) in items:
            no = int(qno)
            qid_mock = f'mock_{sid}_q{no:02d}'
            card_stem = f'{card_stem_base}-q{no:02d}'
            pages = page
            fields = [
                ('type', 'mock_exam_question'),
                ('question_id', qid_mock),
                ('document_id', f'mock_{sid}'),
                ('source_type', 'mock_exam'),
                ('source_title', title),
                ('year', int(year) if year else None),
                ('question_no', no),
                ('page', int(pages) if pages is not None else None),
                ('question_type', qtype),
                ('knowledge_points', None),  # 特殊处理：空数组
                ('legacy_knowledge_points', None),
                ('legacy_knowledge_points_status', '未核验（tex taxonomy 旧模块名）'),
                ('rights_status', rights),
                ('distribution_scope', dist),
                ('internal_only', True),
                ('generated_from', 'postgres'),
                ('generated_at', now),
                ('source_pdf', pdf_field),
                ('answer_pdf', answer_field),
                ('quality', None),
                ('human_edited', False),
            ]
            # 手工拼 frontmatter（knowledge_points / legacy / quality 需要特殊格式）
            fm = ['---']
            for k, v in fields:
                if k == 'knowledge_points':
                    fm.append('knowledge_points: []')
                elif k == 'legacy_knowledge_points':
                    fm.append(yaml_list_block('legacy_knowledge_points', list(kps)))
                elif k == 'quality':
                    fm.append('quality:')
                    fm.append('  ocr_status: needs_review')
                else:
                    fm.append(f'{k}: {yaml_scalar(v)}')
            fm.append('---')
            body = [
                f'# Mock q{no:02d} · {title}',
                '',
                f'> 来源：{title}　｜　页 {pages}　｜　`{rights}` / `{dist}`（仅库内审校，不对外发布）',
                f'> 本套总览：[[{set_name}]]　｜　原始试题 PDF：`{pdf_field}`',
                '',
                '## 题目',
                '',
                md_body(text),
                '',
                '## 答案/解析',
                '',
                '**未入库**：本题答案/解析不在 PostgreSQL（`knowledge_questions.answer_locator` 全部为 NULL）。'
                f'请见答案 PDF：`{answer_field}`' if answer_pdf else
                '**未入库**：本题答案/解析不在 PostgreSQL；'
                f'答案 PDF 在 `{MOCK_PDF_DIR}`（同目录 `__数学答案.pdf`）。',
                '',
                copyright_block(f'原始试题：`{pdf_field}`'),
                '',
            ]
            files.append({'path': folder / f'{card_stem}.md', 'content': '\n'.join(fm + body),
                          'kind': 'mock_card', 'source_id': sid})
            cards.append((no, card_stem, pages))
            stats['cards'] += 1
        # set note
        pages_all = [p for _, _, p in cards if p is not None]
        fm = frontmatter([
            ('type', 'mock_exam_set'),
            ('title', title),
            ('source_type', 'mock_exam'),
            ('year', int(year) if year else None),
            ('question_count', len(cards)),
            ('page_range', f'{min(pages_all)}-{max(pages_all)}' if pages_all else None),
            ('rights_status', rights),
            ('distribution_scope', dist),
            ('internal_only', True),
            ('generated_from', 'postgres'),
            ('generated_at', now),
            ('source_id', f'mock_{sid}'),
            ('source_pdf', pdf_field),
            ('answer_pdf', answer_field),
            ('human_edited', False),
        ])
        body = [
            f'# {title}',
            '',
            f'> 模拟卷（2025）　｜　`{rights}` / `{dist}`　｜　{len(cards)} 题　｜　'
            f'页 {min(pages_all)}–{max(pages_all)}' if pages_all else
            f'> 模拟卷（2025）　｜　`{rights}` / `{dist}`　｜　{len(cards)} 题',
            '',
            '## 来源与版权',
            '',
            f'- 原始试题 PDF：`{pdf_field}`',
            f'- 答案 PDF：`{answer_field}`（答案/解析**未入库**）',
            f'- PostgreSQL source：`{sid}`（`knowledge_sources`）',
            '- `rights_status: restricted`　`distribution_scope: classroom`　`internal_only: true`；'
            '**不对外发布**。',
            '',
            f'## 题目（{len(cards)}）',
            '',
        ]
        for no, stem, page in cards:
            label = f'第 {no} 题' + (f'（第 {page} 页）' if page is not None else '')
            body.append(f'- [[{stem}]] · {label}')
        body += ['', copyright_block('本套为模拟卷，来源分散、许可不明；仅限库内审阅，不得外部分发。'), '']
        files.append({'path': folder / f'{set_name}.md', 'content': '\n'.join([fm] + body),
                      'kind': 'mock_set', 'source_id': sid})
    return files, stats


def build_textbooks(sources, rows, pdf_index, now: str):
    files, stats = [], {'books': 0, 'chunks': 0, 'pdf_exact': 0, 'pdf_fuzzy': 0, 'pdf_none': 0}
    by_source = {}
    for row in rows:
        by_source.setdefault(row[0], []).append(row)
    for sid, title, year, rights, dist, dvid in sources:
        stats['books'] += 1
        items = by_source.get(sid, [])
        stats['chunks'] += len(items)
        key, mode = match_pdf(title, pdf_index)
        if mode == 'exact':
            stats['pdf_exact'] += 1
        elif mode and mode.startswith('fuzzy'):
            stats['pdf_fuzzy'] += 1
        else:
            stats['pdf_none'] += 1
        pdf = pdf_index[key] if key else None
        pdf_field = str(pdf) if pdf else str(TB_PDF_DIR)

        # 目标目录：必修第一册 / 必修第二册 / 选择性必修第一册/二/三册
        m = re.search(r'(选择性必修第[一二三]册|必修第[一二]册)', title)
        if not m:
            raise RuntimeError(f'教材标题无法识别册别：{title}')
        vol = m.group(1)
        folder = TB_ROOT / vol
        if vol.startswith('选择性必修'):
            folder = TB_ROOT / '选择性必修' / vol

        pages = {}
        for (sid2, chunk_key, ordinal, text, page, part, cid) in items:
            if page is None:
                continue
            pages.setdefault(int(page), []).append((int(part or 0), chunk_key, text))
        page_range = f'{min(pages)}-{max(pages)}' if pages else None
        fm = frontmatter([
            ('type', 'textbook'),
            ('textbook_title', title),
            ('source_type', 'textbook'),
            ('volume', vol),
            ('rights_status', rights),
            ('distribution_scope', dist),
            ('internal_only', True),
            ('generated_from', 'postgres'),
            ('generated_at', now),
            ('source_id', f'tb_{sid}'),
            ('source_pdf', pdf_field),
            ('page_range', page_range),
            ('chunk_count', len(items)),
            ('human_edited', False),
        ])
        body = [f'# {title}', '',
                f'> `{rights}` / `{dist}`　｜　{len(items)} 块 / 共 {len(pages)} 页　｜　页范围 {page_range}', '',
                '## 来源与版权', '',
                f'- 原始 PDF：`{pdf_field}`',
                f'- PostgreSQL source：`{sid}`（`knowledge_sources`）',
                '- 人教A版教材版权归人民教育出版社；`rights_status: restricted`、`distribution_scope: classroom`，'
                '**仅限库内审阅，不对外发布**。',
                '',
                '> 本笔记仅按 OCR 页码顺序投影原文，**不伪造章节结构**（PG 无章节元数据）；'
                '章节归属需后续人工整理。', '']
        for page in sorted(pages):
            body.append(f'## 第 {page} 页')
            body.append('')
            for _part, _key, text in pages[page]:
                body.append(md_body(text))
                body.append('')
        body += ['', copyright_block('教材原文仅供库内审校，禁止外部分发。'), '']
        files.append({'path': folder / f'{vol}.md', 'content': '\n'.join([fm] + body),
                      'kind': 'textbook', 'source_id': sid})
    return files, stats


# ---------------------------------------------------------------- 总览
REGION_KEYS = [
    ('上海', '上海'), ('浦东', '上海'), ('四川', '四川'), ('绵阳', '四川'), ('南充', '四川'),
    ('成都', '四川'), ('重庆', '重庆'), ('海南', '海南'), ('天津', '天津'), ('东北', '东北'),
    ('哈师大', '东北'), ('辽宁', '东北'), ('吉林', '东北'), ('黑龙江', '东北'),
    ('河南', '河南'), ('河北', '河北'), ('广西', '广西'), ('山西', '山西'), ('山东', '山东'),
    ('江苏', '江苏'), ('浙江', '浙江'), ('福建', '福建'), ('安徽', '安徽'), ('江西', '江西'),
    ('湖北', '湖北'), ('湖南', '湖南'), ('广东', '广东'), ('陕西', '陕西'), ('甘肃', '甘肃'),
    ('贵州', '贵州'), ('云南', '云南'), ('新疆', '新疆'), ('内蒙古', '内蒙古'), ('北京', '北京'),
]


def guess_region(title: str) -> str:
    for kw, region in REGION_KEYS:
        if kw in title:
            return region
    return '未标注'


def build_indexes(mock_data, tb_data, now: str):
    """mock_data: [(title, year, count, page_range, folder, safe, rights, dist)]；tb_data 类似。"""
    # 模拟题总览
    total_q = sum(d[2] for d in mock_data)
    fm = frontmatter([
        ('type', 'index'), ('title', '模拟题总览'), ('updated', TODAY),
        ('rights_status', 'restricted'), ('distribution_scope', 'classroom'),
        ('internal_only', True), ('generated_from', 'postgres'),
        ('generated_at', now), ('source', 'PostgreSQL knowledge_sources/knowledge_chunks（mock_exam）'),
        ('human_edited', False),
    ])
    body = ['# 模拟题总览（restricted）', '',
            f'> {len(mock_data)} 套 / {total_q} 题　｜　`restricted` / `classroom`　｜　'
            '**答案/解析未入库**（PG `answer_locator` 全为 NULL）　｜　仅限库内审校，不对外发布。', '',
            '## 概况', '',
            '| 项 | 值 |', '| --- | --- |',
            f'| 套数 | {len(mock_data)} |',
            f'| 题数 | {total_q} |',
            '| 年份 | 2025（全部） |',
            '| 地区元数据 | DB `region` 为空；下表地区由标题推断，仅作分组参考 |',
            f'| 答案/解析 | **未入库**；答案 PDF '
            f'{len(list(MOCK_PDF_DIR.glob("*__数学答案.pdf")))} 份在 `{MOCK_PDF_DIR}`（`__数学答案.pdf`） |',
            '| 版权 | `rights_status=restricted`、`distribution_scope=classroom`、`internal_only=true` |', '',
            '## 按年份 / 地区', '', f'### 2025 年（{len(mock_data)} 套 / {total_q} 题）', '',
            '| 套 | 地区（标题推断） | 题数 | 页范围 | 笔记 |', '| --- | --- | --- | --- | --- |']
    for title, year, count, prange, safe, rights, dist in sorted(
            mock_data, key=lambda x: (guess_region(x[0]), x[0])):
        body.append(f'| {title} | {guess_region(title)} | {count} | {prange or "—"} | [[{safe}]] |')
    body += ['', '## 版权与使用边界', '',
             '- 模拟卷来源分散、许可不明：**仅限库内审阅**，不得对外发布或再分发。',
             '- 本页由 `tools/project_restricted_corpus.py` 从 PG 生成（`generated_from: postgres`），'
             '人工可改但请置 `human_edited: true`。',
             '- 答案/解析未入库；若后续补齐，请更新 PG 后重新投影（`--force-generated`）。', '']
    files = [{'path': MOCK_INDEX, 'content': '\n'.join([fm] + body), 'kind': 'index'}]

    # 教材总览
    fm = frontmatter([
        ('type', 'index'), ('title', '教材总览'), ('updated', TODAY),
        ('rights_status', 'restricted'), ('distribution_scope', 'classroom'),
        ('internal_only', True), ('generated_from', 'postgres'),
        ('generated_at', now), ('source', 'PostgreSQL knowledge_chunks（textbook）'),
        ('human_edited', False),
    ])
    body = ['# 教材总览（restricted）', '',
            f'> {len(tb_data)} 册 / {sum(d[2] for d in tb_data)} 块　｜　`restricted` / `classroom`　｜　'
            '人教A版版权归人民教育出版社，仅限库内审校，不对外发布。', '',
            '## 概况', '',
            '| 册 | 块数 | 页范围 | 笔记 |', '| --- | --- | --- | --- |']
    for title, vol, chunks, prange, safe, rights, dist in tb_data:
        body.append(f'| {vol} | {chunks} | {prange or "—"} | [[{vol}]] |')
    body += ['', '## 说明', '',
             '- 教材笔记按 OCR 页码投影原文，**不伪造章节结构**（PG 无章节元数据）。',
             '- 全部为 `restricted` / `classroom`；人教A版 PDF 不在 CC 范围内，禁止外部分发。',
             '- 本页由 `tools/project_restricted_corpus.py` 从 PG 生成（`generated_from: postgres`）。', '']
    files.append({'path': TB_INDEX, 'content': '\n'.join([fm] + body), 'kind': 'index'})
    return files


# ---------------------------------------------------------------- 已有文件判定
def read_head(path: pathlib.Path, n: int = 4096) -> str:
    try:
        with path.open('r', encoding='utf-8', errors='replace') as fh:
            return fh.read(n)
    except OSError:
        return ''


def classify_existing(path: pathlib.Path, new_content: str):
    """返回 write / unchanged / skip_human / skip_foreign / skip_conflict。"""
    if not path.exists():
        return 'write'
    head = read_head(path)
    human = re.search(r'^human_edited:\s*true', head, re.M) is not None
    generated = ('generated_from: postgres' in head
                 and re.search(r'^human_edited:\s*false', head, re.M) is not None)
    if human:
        return 'skip_human'
    if not generated:
        return 'skip_foreign'
    try:
        old = path.read_text(encoding='utf-8')
    except OSError:
        old = head
    if strip_generated_at(old) == strip_generated_at(new_content):
        return 'unchanged'
    return 'skip_conflict'


# ---------------------------------------------------------------- 文档更新（非整文件生成）
def plan_doc_updates(mock_stats, tb_stats, mode):
    """返回 [(path, kind, replacements, marker, block)]；replacements 为 [(old,new)]。"""
    mock_count = mock_stats['sources']
    mock_q = mock_stats['cards']
    tb_count = tb_stats['books']
    tb_chunks = tb_stats['chunks']
    updates = []

    home_block = '\n'.join([
        MARK_MOCK,
        f'- 模拟题：**{mock_count} 套 / {mock_q} 题**（`restricted` / `classroom`，答案/解析未入库；'
        '见 [[模拟题总览]]）',
        f'- 题目总数：**{mock_q + 6050} 题**（高考 6050 + 模拟 {mock_q}）',
        MARK_MOCK.replace('BEGIN', 'END'),
    ])
    updates.append({
        'path': HOME, 'kind': 'home',
        'marker': MARK_MOCK,
        'replacements': [
            ('- 题目：**6050 条**，全部 `needs_review`',
             '- 高考题目：**6050 条**（274 份），全部 `needs_review`'),
            ('- 教材：0 册（`03_Textbooks` 待接入）',
             f'- 教材：**{tb_count} 册 / {tb_chunks} 块**（`restricted` / `classroom`，已投影内部审校区；'
             '见 [[教材总览]]）\n' + home_block),
            ('- [[全库标注总结]]', '- [[全库标注总结]]\n- [[模拟题总览]]\n- [[教材总览]]'),
        ],
    })

    rights_block = '\n'.join([
        '## 7. 受限资料投影（生成）', '',
        MARK_TB,
        f'- 模拟题：{mock_count} 套 / {mock_q} 题 → `04_Exams/MockExams/2025/`；'
        '答案/解析**未入库**，答案 PDF 在 `corpus/mock-exams`。',
        f'- 教材：{tb_count} 册 / {tb_chunks} 块 → `03_Textbooks/`；按 OCR 页码投影，无章节结构。',
        '- 两者 PG 均 `rights_status=restricted`、`distribution_scope=classroom`：'
        '**已投影进 Obsidian 内部审校区，不对外发布**。',
        '- 生成物带 `generated_from: postgres` / `internal_only: true` / 版权段；投影工具 '
        '`tools/project_restricted_corpus.py`。',
        MARK_TB.replace('BEGIN', 'END'),
    ])
    updates.append({
        'path': RIGHTS, 'kind': 'rights',
        'marker': MARK_TB,
        'replacements': [
            (f'| 人教版教材 PDF | `{TB_PDF_DIR}`（人教A版） | **未解决** | 未入库 |',
             f'| 人教版教材 PDF | `{TB_PDF_DIR}`（人教A版） | **PEP 版权（内部使用）** | '
             f'已投影 Obsidian 内部审校区（{tb_count} 册 / {tb_chunks} 块；`restricted`/`classroom`，不对外发布） |'),
            (f'| 模拟卷 | `{MOCK_PDF_DIR}` | **未解决**（各校来源不明） | 未入库 |',
             f'| 模拟卷 | `{MOCK_PDF_DIR}` | **未解决**（各校来源不明） | '
             f'已投影 Obsidian 内部审校区（{mock_count} 套 / {mock_q} 题；`restricted`/`classroom`，不对外发布；'
             '答案/解析未入库） |'),
        ],
        'append_block': rights_block,
    })

    migration_block = '\n'.join([
        f'**{TODAY} · 受限资料投影（模拟题 + 教材 → Obsidian 内部审校区）**：',
        '',
        '| 项 | 内容 |',
        '| --- | --- |',
        f'| 输入 | PG `knowledge_sources`/`knowledge_chunks`：mock_exam {mock_count} 套 / {mock_q} 题；'
        f'textbook {tb_count} 册 / {tb_chunks} 块（PG 是 SSOT） |',
        f'| 输出 | `04_Exams/MockExams/2025/<套>/`（{mock_count} set + {mock_q} 卡）；'
        f'`03_Textbooks/`（{tb_count} 册）；`10_Indexes/模拟题总览.md`、`教材总览.md` |',
        '| 版权 | 两者均 `rights_status=restricted`、`distribution_scope=classroom`、`internal_only=true`；'
        '已投影进 Obsidian 内部审校区，不对外发布 |',
        '| 答案 | **答案/解析未入库**（PG `answer_locator` 全 NULL）；答案 PDF 在 `corpus/mock-exams` 同目录 |',
        '| 安全 | 只写 generated_from=postgres 且 human_edited=false 的文件；默认不覆盖已有文件；高考卡 0 改动 |',
        '| 工具 | `tools/project_restricted_corpus.py`（dry-run 默认 / `--apply` / `--only` / `--force-generated`） |',
        '| 契约 | `docs/KB_SYNC_CONTRACT.md`「受限资料投影」一节 |',
        '',
    ])
    updates.append({
        'path': MIGRATION, 'kind': 'migration',
        'marker': '受限资料投影（模拟题 + 教材 → Obsidian 内部审校区）',
        'append_block': migration_block,
    })
    return updates


def apply_doc_updates(updates, dry_run: bool, report):
    results = []
    for u in updates:
        path = u['path']
        txt = path.read_text(encoding='utf-8') if path.exists() else ''
        marker = u['marker']
        if marker in txt:
            results.append({'path': str(path), 'kind': u['kind'], 'status': 'unchanged'})
            continue
        new = txt
        ok = True
        for old, repl in u.get('replacements', []):
            if old not in new:
                ok = False
                report['doc_warnings'].append(f'{u["kind"]}: 未找到预期文本，跳过该替换：{old[:60]}')
                continue
            new = new.replace(old, repl, 1)
        if u.get('append_block'):
            block = u['append_block']
            if '## 7. 受限资料投影（生成）' in new:
                # 已存在标题但无 marker（异常）：只在文末追加块
                pass
            new = new.rstrip() + '\n\n' + block + '\n'
        if new == txt:
            results.append({'path': str(path), 'kind': u['kind'], 'status': 'unchanged'})
            continue
        if dry_run:
            results.append({'path': str(path), 'kind': u['kind'], 'status': 'would_update'})
            continue
        path.write_text(new, encoding='utf-8')
        results.append({'path': str(path), 'kind': u['kind'], 'status': 'updated'})
    return results


# ---------------------------------------------------------------- 主流程
def gk_signature() -> tuple:
    root = VAULT / '04_Exams' / 'Gaokao'
    if not root.exists():
        return 0, ''
    h = hashlib.sha256()
    count = 0
    for p in sorted(root.rglob('*.md')):
        count += 1
        h.update(str(p.relative_to(VAULT)).encode('utf-8'))
        h.update(b'\0')
        h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode())
        h.update(b'\n')
    return count, h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description='PG → Obsidian：受限资料（模拟题/教材）投影')
    ap.add_argument('--vault', default=os.environ.get('CHILON_VAULT'),
                    help='Obsidian vault 根目录；默认读环境变量 CHILON_VAULT，两者都没有时报错')
    ap.add_argument('--database-url', default=None,
                    help='PostgreSQL 连接串；默认读 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL，'
                         '都没有时回退到当前本机容器 env')
    ap.add_argument('--apply', action='store_true', help='真正写文件（默认 dry-run）')
    ap.add_argument('--only', choices=['mock', 'textbook'], help='只投影其中一种')
    ap.add_argument('--force-generated', action='store_true',
                    help='刷新本工具以前生成的文件（generated_from=postgres 且 human_edited=false）')
    ap.add_argument('--report', default=str(OUT / 'report.md'))
    ap.add_argument('--manifest', default=str(OUT / 'manifest.json'))
    args = ap.parse_args(argv)

    # vault：--vault → CHILON_VAULT；两者都没有时干净报错（argparse 用法提示，退出码 2）
    vault_arg = args.vault or os.environ.get('CHILON_VAULT')
    if not vault_arg:
        ap.error('必须提供 --vault 或 CHILON_VAULT')
    vault_path = pathlib.Path(vault_arg).expanduser()
    if not vault_path.is_dir():
        ap.error(f'vault 目录不存在：{vault_path}')
    _set_vault(vault_path)  # 更新 VAULT 及其派生路径全局变量

    mode = 'apply' if args.apply else 'dry-run'

    OUT.mkdir(parents=True, exist_ok=True)
    now_dt = _dt.datetime.now().astimezone()
    now = now_dt.strftime('%Y-%m-%dT%H:%M:%S%z')
    report = {'mode': mode, 'generated_at': now, 'counts': {}, 'files': [],
              'doc_warnings': [], 'skips': [], 'writes': 0, 'unchanged': 0, 'errors': []}
    print('=' * 78)
    print('PG → Obsidian：受限资料投影（模拟题 / 教材）')
    print(f'模式：{mode}　only={args.only or "all"}　force_generated={args.force_generated}')
    print(f'vault：{VAULT}')
    print('=' * 78)

    try:
        url, dblabel = _db_url(args.database_url)
    except RuntimeError as e:
        print(f'[失败] {e}', file=sys.stderr)
        return 3
    print(f'DB：{dblabel}')
    try:
        conn = psycopg.connect(url)
        mock_sources, mock_rows, tb_sources, tb_rows = fetch_data(conn)
        conn.close()
    except Exception as e:  # noqa: BLE001
        print(f'[失败] 数据库读取失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 3
    report['db'] = dblabel
    print(f'[读库] mock {len(mock_sources)} 套 / {len(mock_rows)} chunks；'
          f'textbook {len(tb_sources)} 册 / {len(tb_rows)} chunks')
    if len(mock_sources) != 67 or len(mock_rows) != 931 or len(tb_sources) != 5 or len(tb_rows) != 1797:
        print(f'[失败] 数量与预期不符（期望 67/931/5/1797）', file=sys.stderr)
        return 2
    if any(r[5] is None for r in mock_rows):
        print('[失败] mock chunk 未 1:1 匹配到 question（answer_locator/题号缺失会破坏卡片 ID）',
              file=sys.stderr)
        return 2

    # 文件名安全化后的冲突检查（冲突需人工处理，避免静默覆盖）
    safe_titles = [safe_name(s[1]) for s in mock_sources]
    if len(set(safe_titles)) != len(safe_titles):
        dup = [k for k, v in collections.Counter(safe_titles).items() if v > 1]
        print(f'[失败] 模拟卷标题清理后文件名冲突：{dup}，请人工处理后再投影', file=sys.stderr)
        return 2

    mock_pdf, tb_pdf = build_pdf_index()
    files, mock_stats = [], {'sources': 0, 'cards': 0, 'pdf_exact': 0, 'pdf_fuzzy': 0, 'pdf_none': 0}
    tb_stats = {'books': 0, 'chunks': 0, 'pdf_exact': 0, 'pdf_fuzzy': 0, 'pdf_none': 0}
    if args.only != 'textbook':
        mock_files, mock_stats = build_mock(mock_sources, mock_rows, mock_pdf, now)
        files += mock_files
        report['counts']['mock_sources'] = len(mock_sources)
        report['counts']['mock_cards'] = len([f for f in mock_files if f['kind'] == 'mock_card'])
        report['counts']['mock_sets'] = len([f for f in mock_files if f['kind'] == 'mock_set'])
    if args.only != 'mock':
        tb_files, tb_stats = build_textbooks(tb_sources, tb_rows, tb_pdf, now)
        files += tb_files
        report['counts']['textbooks'] = len([f for f in tb_files if f['kind'] == 'textbook'])
        report['counts']['textbook_chunks'] = len(tb_rows)
    if args.only is None:
        idx_files = build_indexes(
            [(s[1], s[2], sum(1 for r in mock_rows if r[0] == s[0]),
              (lambda rr: f'{min(rr)}-{max(rr)}' if rr else None)(
                  [r[9] for r in mock_rows if r[0] == s[0]]),
              safe_name(s[1]), s[3], s[4]) for s in mock_sources],
            [(s[1], re.search(r'(选择性必修第[一二三]册|必修第[一二]册)', s[1]).group(1),
              sum(1 for r in tb_rows if r[0] == s[0]),
              (lambda rr: f'{min(rr)}-{max(rr)}' if rr else None)(
                  [r[4] for r in tb_rows if r[0] == s[0]]),
              safe_name(s[1]), s[3], s[4]) for s in tb_sources],
            now)
        files += idx_files
        report['counts']['indexes'] = len(idx_files)

    # 判定每个目标文件
    plan = {'write': [], 'unchanged': [], 'skip_human': [], 'skip_foreign': [], 'skip_conflict': []}
    for f in files:
        path = pathlib.Path(f['path'])
        status = classify_existing(path, f['content'])
        if status == 'skip_conflict' and args.force_generated:
            status = 'write'
        plan[status].append(str(path))
        f['status'] = status
    for k in ('skip_human', 'skip_foreign', 'skip_conflict'):
        report['skips'] += [{'path': p, 'status': k} for p in plan[k]]
    report['planned_write'] = len(plan['write'])
    report['files'] = [{'path': str(f['path']), 'kind': f['kind'], 'status': f['status'],
                        'sha256': sha256_text(f['content'])} for f in files]

    # 文档更新（仅全量投影时执行；--only 不改索引/状态文档）
    doc_results = []
    if args.only is None:
        doc_updates = plan_doc_updates(mock_stats, tb_stats, mode)
        doc_results = apply_doc_updates(doc_updates, dry_run=(mode == 'dry-run'), report=report)
    report['doc_updates'] = doc_results
    report['pdf'] = {'mock': mock_stats, 'textbook': tb_stats}

    print(f'[计划] 文件：write={len(plan["write"])} unchanged={len(plan["unchanged"])} '
          f'skip_human={len(plan["skip_human"])} skip_foreign={len(plan["skip_foreign"])} '
          f'skip_conflict={len(plan["skip_conflict"])}')
    print(f'        模拟：{mock_stats["sources"]} set / {mock_stats["cards"]} 卡；'
          f'教材：{tb_stats["books"]} 册 / {tb_stats["chunks"]} 块；'
          f'索引：{report["counts"].get("indexes", 0)}')
    print(f'        PDF 匹配：mock exact={mock_stats["pdf_exact"]} fuzzy={mock_stats["pdf_fuzzy"]} '
          f'none={mock_stats["pdf_none"]}；教材 exact={tb_stats["pdf_exact"]} '
          f'fuzzy={tb_stats["pdf_fuzzy"]} none={tb_stats["pdf_none"]}')
    print(f'[文档] ' + '；'.join(f'{d["kind"]}={d["status"]}' for d in doc_results))
    if report['doc_warnings']:
        for w in report['doc_warnings']:
            print(f'        [警告] {w}')

    gk_before = gk_signature()
    report['gk_before'] = {'count': gk_before[0], 'sha256': gk_before[1]}

    if mode == 'apply':
        for f in files:
            if f['status'] != 'write':
                continue
            path = pathlib.Path(f['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f['content'], encoding='utf-8')
            report['writes'] += 1
        report['unchanged'] = len(plan['unchanged'])
        gk_after = gk_signature()
        report['gk_after'] = {'count': gk_after[0], 'sha256': gk_after[1]}
        report['gk_ok'] = gk_before == gk_after
        # 验证：全部生成物都带标记
        missing = []
        for f in files:
            if f['status'] not in ('write', 'unchanged'):
                continue
            head = read_head(pathlib.Path(f['path']))
            if not ('generated_from: postgres' in head and 'rights_status: restricted' in head
                    and 'human_edited: false' in head):
                missing.append(f['path'])
        report['marker_missing'] = missing
        print(f'[写入] 新写 {report["writes"]} 个文件；幂等不变 {report["unchanged"]}；'
              f'跳过 {len(report["skips"])}')
        print(f'[高考卡] {gk_before[0]} 张，聚合 sha256 {gk_before[1][:16]}… → '
              f'{gk_after[0]} 张，sha256 {gk_after[1][:16]}…　'
              f'{"✅ 未变" if report["gk_ok"] else "❌ 有变化！"}')
        if missing:
            print(f'[警告] {len(missing)} 个生成物缺版权/来源标记（见报告）')
        # 抽查
        samples = pick_samples(files, report)
        report['samples'] = samples
        for s in samples:
            print(f'[抽查] {s["path"]}（{s["bytes"]}B）{s["first_line"]}')
    else:
        print('[dry-run] 未写任何文件。确认后加 --apply。')
        report['gk_after'] = report['gk_before']

    # 写报告 / manifest
    write_report(report, pathlib.Path(args.report))
    manifest_path = pathlib.Path(args.manifest)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'\n报告：{args.report}')
    print(f'manifest：{args.manifest}')
    return 0


def pick_samples(files, report):
    def first_title(text):
        for line in text.splitlines():
            if line.startswith('# '):
                return line
        return text.splitlines()[0] if text else ''

    samples = []
    mock_cards = [f for f in files if f['kind'] == 'mock_card' and f['status'] in ('write', 'unchanged')]
    tb_notes = [f for f in files if f['kind'] == 'textbook' and f['status'] in ('write', 'unchanged')]
    for f in mock_cards[:3]:
        p = pathlib.Path(f['path'])
        text = f['content']
        samples.append({'path': str(p.relative_to(VAULT)) if str(p).startswith(str(VAULT)) else str(p),
                        'bytes': len(text.encode('utf-8')),
                        'first_line': first_title(text)})
    for f in tb_notes[:2]:
        p = pathlib.Path(f['path'])
        text = f['content']
        page_heads = [ln for ln in text.splitlines() if ln.startswith('## 第 ')][:3]
        samples.append({'path': str(p.relative_to(VAULT)) if str(p).startswith(str(VAULT)) else str(p),
                        'bytes': len(text.encode('utf-8')),
                        'first_line': first_title(text) + ' ｜ 页面：' + '、'.join(page_heads)})
    return samples


def write_report(report, path):
    counts = report['counts']
    L = ['---', 'type: data', f'updated: {TODAY}',
         f'title: 受限资料投影报告（{report["mode"]}）', '---', '',
         '# 受限资料投影报告（模拟题 / 教材 → Obsidian）', '',
         f'> 模式：**{report["mode"]}**　｜　生成：{report["generated_at"]}  ',
         f'> 数据库：{report.get("db", "—")}  ',
         '> 版权：全部 `rights_status=restricted`、`distribution_scope=classroom`、`internal_only=true`；'
         '仅限库内审校，不对外发布。', '',
         '## 1. 计数', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| 模拟题套数（set note） | {counts.get("mock_sets", 0)} |',
         f'| 模拟题卡片 | {counts.get("mock_cards", 0)} |',
         f'| 教材笔记 | {counts.get("textbooks", 0)} |',
         f'| 教材 chunk（原文块） | {counts.get("textbook_chunks", 0)} |',
         f'| 索引（总览） | {counts.get("indexes", 0)} |',
         f'| 计划写入文件 | {report.get("planned_write", report["writes"])} |',
         f'| 本次新写文件 | {report["writes"]} |',
         f'| 幂等不变 | {report["unchanged"]} |',
         f'| 跳过（人工/既有/冲突） | {len(report["skips"])} |', '']
    L += ['## 2. PDF 匹配', '', '| 类型 | exact | fuzzy | 未匹配 |', '| --- | --- | --- | --- |',
          f'| 模拟题（试题/答案） | {report["pdf"]["mock"]["pdf_exact"]} | '
          f'{report["pdf"]["mock"]["pdf_fuzzy"]} | {report["pdf"]["mock"]["pdf_none"]} |',
          f'| 教材 | {report["pdf"]["textbook"]["pdf_exact"]} | '
          f'{report["pdf"]["textbook"]["pdf_fuzzy"]} | {report["pdf"]["textbook"]["pdf_none"]} |', '',
          '> 匹配失败时 `source_pdf` 写目录，正文提示同目录答案 PDF。', '']
    L += ['## 3. 文档更新', '', '| 文档 | 状态 |', '| --- | --- |']
    for d in report['doc_updates']:
        L.append(f'| `{pathlib.Path(d["path"]).name}` | {d["status"]} |')
    L += ['']
    if report['doc_warnings']:
        L += ['**警告**：', ''] + [f'- {w}' for w in report['doc_warnings']] + ['']
    L += ['## 4. 跳过 / 冲突', '']
    if report['skips']:
        L += ['| 文件 | 原因 |', '| --- | --- |']
        L += [f'| `{s["path"]}` | {s["status"]} |' for s in report['skips'][:50]]
        if len(report['skips']) > 50:
            L.append(f'| …（共 {len(report["skips"])} 条） | |')
    else:
        L.append('无。')
    L += ['', '## 5. 高考卡验证', '',
          f'- 投影前：{report["gk_before"]["count"]} 张，聚合 sha256 `{report["gk_before"]["sha256"][:16]}…`',
          f'- 投影后：{report["gk_after"]["count"]} 张，聚合 sha256 `{report["gk_after"]["sha256"][:16]}…`',
          f'- 结论：**{"未改动" if report.get("gk_ok", True) else "有改动（需排查！）"}**', '',
          '## 6. 抽查', '']
    for s in report.get('samples', [])[:6]:
        L.append(f'- `{s["path"]}`（{s["bytes"]} B）：{s["first_line"]}')
    L += ['', '## 7. 安全与版权', '',
          '- 只写 `generated_from: postgres` 且 `human_edited: false` 的文件；人工编辑文件跳过。',
          '- 默认不覆盖已有文件；`--force-generated` 只刷新本工具生成的文件。',
          '- 答案/解析未入库（PG `answer_locator` 全 NULL）；卡片只写“见同目录答案 PDF”，不伪造答案。',
          '- 所有生成物带版权段与 `restricted`/`classroom`/`internal_only` 标记；不对外发布。',
          '- 数据库密码不落文件、不进报告（取自容器 env / 环境变量）。', '',
          '## 8. 复现', '', '```powershell',
          '$env:CHILON_VAULT = "<vault 路径>"',
          '$env:CHILON_TEST_DATABASE_URL = "<连接串>"   # 或 --database-url',
          '.\\\\.venv\\\\Scripts\\\\python.exe tools/project_restricted_corpus.py --vault "<vault>"            # dry-run',
          '.\\\\.venv\\\\Scripts\\\\python.exe tools/project_restricted_corpus.py --vault "<vault>" --apply    # 写入',
          '```', '',
          '> `--database-url` 显式覆盖连接串；未提供时依次读 CHILON_TEST_DATABASE_URL、'
          'CHILON_DATABASE_URL，最后回退容器 env。密码从不打印/落盘。', '']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(L), encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
