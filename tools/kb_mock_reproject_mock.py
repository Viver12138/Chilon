#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在 chunk 拆分后重新投影模拟题卡（等效于 project_restricted_corpus.py --only mock --force-generated，
适配 PG 中 mock chunk 数因 split 变为 993 的情况：本工具只取与 question 通过 locator 关联的 931 个 chunk）。

- 只写 vault `04_Exams/MockExams/**`（931 卡 + 67 set note）；
- 只覆盖 generated_from=postgres 且 human_edited=false 的文件；
- 校验高考卡 0 改动（调用 project 工具的 gk_signature）；
- 不写 PG、不调 OCR、不改索引/其他 vault 文件。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

try:
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    print('缺少 psycopg：请用 .venv 运行', file=sys.stderr)
    sys.exit(4)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJ = ROOT / 'tools' / 'project_restricted_corpus.py'
OUT = ROOT / 'var' / 'mock_repair'
CONTAINER = 'chilon-pg-corpus'


def db_url(arg=None):
    if arg:
        return arg, '--database-url'
    for env in ('CHILON_TEST_DATABASE_URL', 'CHILON_DATABASE_URL'):
        if os.environ.get(env):
            return os.environ[env], f'环境变量 {env}'
    pw = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                        capture_output=True, text=True).stdout.strip()
    if not pw:
        raise RuntimeError('无法读取容器 env')
    return (f'postgresql://postgres:{urllib.parse.quote(pw)}@127.0.0.1:55495/chilon',
            f'容器 {CONTAINER} env')


def main():
    spec = importlib.util.spec_from_file_location('proj', PROJ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    vault = os.environ.get('CHILON_VAULT')
    if not vault:
        print('[失败] 需要 CHILON_VAULT 或用环境变量指定 vault', file=sys.stderr)
        return 2
    m._set_vault(pathlib.Path(vault))
    url, dblabel = db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id::text, s.title, s.year, s.rights_status, s.distribution_scope,
               dv.id::text, dv.storage_key, s.created_at::text
        FROM knowledge_sources s JOIN knowledge_document_versions dv ON dv.source_id=s.id
        WHERE s.source_type='mock_exam' ORDER BY s.title
    """)
    sources = cur.fetchall()
    cur.execute("""
        SELECT s.id::text, c.chunk_key, c.ordinal, c.locator, c.text_content,
               q.id::text, q.question_no, q.current_paper_question_type,
               coalesce(q.current_knowledge_points,'{}'),
               (c.locator->>'page_number')::int, (c.locator->>'question_index')::int, c.id::text
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        JOIN knowledge_chunks c ON c.document_version_id=q.document_version_id AND c.locator=q.stem_locator
        WHERE s.source_type='mock_exam'
        ORDER BY s.title, q.question_no::int
    """)
    rows = cur.fetchall()
    conn.close()
    print(f'[读库] mock {len(sources)} 套 / {len(rows)} linked chunks（DB：{dblabel}）')
    if len(sources) != 67 or len(rows) != 931:
        print(f'[失败] 数量不符（期望 67/931）', file=sys.stderr)
        return 2
    now = __import__('datetime').datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')
    pdf, _tb = m.build_pdf_index()
    files, stats = m.build_mock(sources, rows, pdf, now)
    print(f'[生成] set {sum(1 for f in files if f["kind"]=="mock_set")}｜卡 '
          f'{sum(1 for f in files if f["kind"]=="mock_card")}｜PDF exact {stats["pdf_exact"]}')
    gk_before = m.gk_signature()
    written = unchanged = skipped = 0
    for f in files:
        p = pathlib.Path(f['path'])
        status = m.classify_existing(p, f['content'])
        if status == 'skip_conflict':
            status = 'write'  # --force-generated 语义
        if status == 'write':
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f['content'], encoding='utf-8')
            written += 1
        elif status == 'unchanged':
            unchanged += 1
        else:
            skipped += 1
            print(f'[跳过 {status}] {p}')
    gk_after = m.gk_signature()
    OUT.mkdir(parents=True, exist_ok=True)
    L = ['---', 'type: data', 'title: 模拟题卡重投影报告（修复后）', 'updated: 2026-11-06', '---', '',
         '# 模拟题卡重投影报告（chunk 修复后）', '',
         f'> 来源：PG 931 个 linked mock chunk（DB：{dblabel}）；写入 `04_Exams/MockExams/**`。  ',
         '> 只覆盖 generated_from=postgres 且 human_edited=false 的文件；不写 PG、不调 OCR。', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| set note | {sum(1 for f in files if f["kind"]=="mock_set")} |',
         f'| 题卡 | {sum(1 for f in files if f["kind"]=="mock_card")} |',
         f'| 新写/覆盖 | {written} |', f'| 幂等不变 | {unchanged} |', f'| 跳过（人工/外来） | {skipped} |',
         f'| 高考卡（重投影前） | {gk_before[0]} 张 / {gk_before[1][:16]}… |',
         f'| 高考卡（重投影后） | {gk_after[0]} 张 / {gk_after[1][:16]}… |',
         f'| 高考卡是否未变 | {"✅ 未变" if gk_before == gk_after else "❌ 有变化"} |', '',
         '## 校验（重投影内容的来源）', '',
         '- 卡片正文来自 PG question 通过 stem_locator 关联的 chunk 文本（apply 后已校验 894/894 与 repaired 一致）；',
         '- 原始多题 chunk 保留在 PG（traceability），不参与投影；questions 指向新 split chunk；',
         '- 本报告不改索引/说明文档（统计与题目数量未变）。', '']
    (OUT / 'reproject_report.md').write_text('\n'.join(L), encoding='utf-8')
    print(f'[写入] {written}｜幂等不变 {unchanged}｜跳过 {skipped}')
    print(f'[高考卡] {gk_before[0]} → {gk_after[0]}｜未变={"是" if gk_before == gk_after else "否"}')
    print(f'报告：{OUT / "reproject_report.md"}')
    return 0 if (gk_before == gk_after and written + unchanged == 998 and skipped == 0) else 4


if __name__ == '__main__':
    sys.exit(main())
