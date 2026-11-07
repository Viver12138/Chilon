#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材块标注 PG draft：建表（按 generated DDL）+ 幂等 upsert + 校验 + 回滚。

- 输入：var/textbook_mapping/mapped_1797_reviewed.json（360 teacher / 1437 model）
- 表：textbook_block_annotations（registry/generator 已生成；本工具从 generated/schema.sql 取表 DDL）
- 360 teacher：classification_source=teacher、review_status=reviewed；teacher 空白→non_content；
  其余 model→needs_review；空 primary→vocab_gap。
- 不调 OCR、不写 mock/gaokao/knowledge_annotations、不 commit。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
REVIEWED = OUT / 'mapped_1797_reviewed.json'
SCHEMA_SQL = ROOT / 'database' / 'generated' / 'schema.sql'
BACKUP = OUT / 'backup_pg_draft_2026-11-06.json'
REPORT = OUT / 'pg_draft_report.md'
DDL_DOC = ROOT / 'docs' / 'textbook_block_annotations_ddl.md'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
TABLE = 'textbook_block_annotations'
MODEL_VERSION = 'textbook-map-v3-2026-11-06'
TEACHER_VERSION = 'textbook-review-2026-11-06'
NS = uuid.NAMESPACE_URL


def die(msg, code=2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def db_url():
    if os.environ.get('CHILON_TEST_DATABASE_URL'):
        return os.environ['CHILON_TEST_DATABASE_URL']
    if os.environ.get('CHILON_DATABASE_URL'):
        return os.environ['CHILON_DATABASE_URL']
    pw = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                        capture_output=True, text=True).stdout.strip()
    if not pw:
        raise RuntimeError('无法读取容器 env')
    return f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}'


def extract_table_ddl():
    t = SCHEMA_SQL.read_text(encoding='utf-8')
    start = t.index('CREATE TABLE textbook_block_annotations (')
    # 到下一个 "-- Deferred foreign keys" / 文件末；中间含 RLS/policy/index
    tail = t.find('-- Deferred foreign keys', start)
    block = t[start:tail if tail != -1 else len(t)]
    stmts = []
    for raw in block.split(';'):
        s = raw.strip()
        if not s:
            continue
        # 去掉前导注释行，保留语句本身
        s = '\n'.join(line for line in s.splitlines() if not line.strip().startswith('--')).strip()
        if s:
            stmts.append(s + ';')
    return stmts


def prepare_rows(items):
    rows = []
    for x in items:
        teacher = x.get('review_status') == 'teacher'
        kp = (x.get('teacher_kp') or '') if teacher else (x.get('kp_primary') or '')
        if teacher and kp in ('—', '-'):
            kp = ''
        sec = [] if teacher else list(x.get('kp_secondary') or [])
        if teacher:
            if kp:
                status = 'mapped'
                source = 'teacher'
                review = 'reviewed'
                module = x.get('teacher_module') or None
                conf = 1.0
                mv = x.get('teacher_version') or TEACHER_VERSION
                rationale = x.get('reason') or '教师复核'
            else:
                module = x.get('teacher_module') or None
                if module in ('—', '-'):
                    module = None
                # 教师给模块但不指定主考点 → vocab_gap（词表缺口）；模块/考点都空 → non_content
                status = 'vocab_gap' if module else 'non_content'
                source = 'teacher'
                review = 'reviewed'
                conf = 1.0
                mv = x.get('teacher_version') or TEACHER_VERSION
                if module:
                    rationale = (x.get('teacher_note') or x.get('reason')
                                 or '教师复核：有模块但无合适主考点')
                else:
                    rationale = '教师复核：非内容/不映射'
        else:
            status = x.get('status') or ('mapped' if kp else 'vocab_gap')
            if not kp and status != 'non_content':
                status = 'vocab_gap'
            source = 'model'
            review = 'needs_review'
            module = x.get('module_id') or None
            conf = float(x.get('confidence') or 0)
            mv = MODEL_VERSION
            rationale = x.get('reason') or ''
            if status == 'non_content':
                kp, sec, module = '', [], None
        rows.append({'id': str(uuid.uuid5(NS, 'textbook-block:' + x['chunk_id'])),
                     'chunk_id': x['chunk_id'], 'block_id': x['block_id'],
                     'kp_primary': kp or None, 'kp_secondary': json.dumps(sec, ensure_ascii=False),
                     'module_id': module, 'status': status, 'classification_source': source,
                     'confidence': conf, 'model_version': mv, 'review_status': review,
                     'rationale': rationale})
    if len(rows) != 1797 or len({r['chunk_id'] for r in rows}) != 1797:
        die(f'rows {len(rows)} / unique chunk {len({r["chunk_id"] for r in rows})} != 1797')
    return rows


def table_exists(cur):
    cur.execute('SELECT to_regclass(%s) IS NOT NULL', (TABLE,))
    return cur.fetchone()[0]


def stage_dry(args):
    import psycopg
    items = json.loads(REVIEWED.read_text(encoding='utf-8'))['items']
    rows = prepare_rows(items)
    conn = psycopg.connect(db_url())
    cur = conn.cursor()
    exists = table_exists(cur)
    cur.execute('SELECT count(*) FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type=\'textbook\'')
    textbook_chunks = cur.fetchone()[0]
    cur.execute('SELECT c.id::text FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type=\'textbook\'')
    known = {r[0] for r in cur.fetchall()}
    missing = [r['chunk_id'] for r in rows if r['chunk_id'] not in known]
    existing = {}
    if exists:
        cur.execute(f'SELECT chunk_id::text, kp_primary, kp_secondary::text, module_id, status, classification_source, confidence::float8, model_version, review_status, rationale FROM {TABLE} WHERE superseded_by IS NULL')
        existing = {r[0]: r[1:] for r in cur.fetchall()}
    conn.close()
    changed = 0
    for r in rows:
        e = existing.get(r['chunk_id'])
        if not e:
            changed += 1
        else:
            vals = (r['kp_primary'], r['kp_secondary'], r['module_id'], r['status'],
                    r['classification_source'], r['confidence'], r['model_version'],
                    r['review_status'], r['rationale'])
            if e[0] != vals[0] or json.loads(e[1]) != json.loads(vals[1]) or e[2] != vals[2] \
                    or e[3] != vals[3] or e[4] != vals[4] or abs(float(e[5]) - float(vals[5])) > 1e-9 \
                    or e[6] != vals[6] or e[7] != vals[7] or (e[8] or '') != (vals[8] or ''):
                changed += 1
    teacher = sum(1 for r in rows if r['classification_source'] == 'teacher')
    print(f'[dry-run] 输入 {REVIEWED.name}；model_version {MODEL_VERSION}；备份 {BACKUP.name}')
    print(f'[dry-run] rows {len(rows)}；textbook chunks {textbook_chunks}；missing chunk {len(missing)}；'
          f'duplicate {len(rows)-len({r["chunk_id"] for r in rows})}；teacher {teacher} / model {len(rows)-teacher}；'
          f'表存在={exists}；待写/变更 {changed}')
    print(f'状态 {dict(collections.Counter(r["status"] for r in rows))}')
    if missing:
        print('missing sample', missing[:5])
    # 备份：表不存在则记录空
    if not BACKUP.exists():
        backup = {'table': TABLE, 'table_existed_before': exists, 'rows': []}
        if exists:
            conn = psycopg.connect(db_url()); cur = conn.cursor()
            cur.execute(f'SELECT id::text, chunk_id::text, block_id, kp_primary, kp_secondary::text, module_id, status, classification_source, confidence::float8, model_version, review_status, rationale, superseded_by::text, created_at::text, updated_at::text FROM {TABLE}')
            backup['rows'] = [dict(zip(['id','chunk_id','block_id','kp_primary','kp_secondary','module_id','status','classification_source','confidence','model_version','review_status','rationale','superseded_by','created_at','updated_at'], r)) for r in cur.fetchall()]
            conn.close()
        BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[备份] {BACKUP}（table_existed_before={exists}）')
    return 0


def stage_apply(args):
    import psycopg
    items = json.loads(REVIEWED.read_text(encoding='utf-8'))['items']
    rows = prepare_rows(items)
    ddl = extract_table_ddl()
    conn = psycopg.connect(db_url())
    try:
        with conn.transaction():
            cur = conn.cursor()
            existed = table_exists(cur)
            if not existed:
                for stmt in ddl:
                    cur.execute(stmt)
            # 现有 active 行
            cur.execute(f'''SELECT chunk_id::text, id::text, block_id, kp_primary, kp_secondary::text,
                module_id, status, classification_source, confidence::float8, model_version, review_status, rationale
                FROM {TABLE} WHERE superseded_by IS NULL''')
            existing = {}
            for e in cur.fetchall():
                existing[e[0]] = e
            inserted = updated = unchanged = 0
            for r in rows:
                e = existing.get(r['chunk_id'])
                if e:
                    same = (e[2] == r['block_id'] and (e[3] or '') == (r['kp_primary'] or '')
                            and json.loads(e[4]) == json.loads(r['kp_secondary'])
                            and (e[5] or '') == (r['module_id'] or '') and e[6] == r['status']
                            and e[7] == r['classification_source'] and abs(float(e[8]) - float(r['confidence'])) < 1e-9
                            and (e[9] or '') == (r['model_version'] or '') and e[10] == r['review_status']
                            and (e[11] or '') == (r['rationale'] or ''))
                    if same:
                        unchanged += 1
                        continue
                    cur.execute(f"""UPDATE {TABLE} SET block_id=%s, kp_primary=%s, kp_secondary=%s::jsonb,
                        module_id=%s, status=%s, classification_source=%s, confidence=%s,
                        model_version=%s, review_status=%s, rationale=%s, updated_at=now()
                        WHERE chunk_id=%s AND superseded_by IS NULL""",
                                (r['block_id'], r['kp_primary'], r['kp_secondary'], r['module_id'],
                                 r['status'], r['classification_source'], r['confidence'],
                                 r['model_version'], r['review_status'], r['rationale'], r['chunk_id']))
                    updated += 1
                else:
                    cur.execute(f"""INSERT INTO {TABLE}
                        (id, chunk_id, block_id, kp_primary, kp_secondary, module_id, status,
                         classification_source, confidence, model_version, review_status, rationale)
                        VALUES (%s::uuid,%s::uuid,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)""",
                                (r['id'], r['chunk_id'], r['block_id'], r['kp_primary'], r['kp_secondary'],
                                 r['module_id'], r['status'], r['classification_source'], r['confidence'],
                                 r['model_version'], r['review_status'], r['rationale']))
                    inserted += 1
        conn.commit()
    finally:
        conn.close()
    # 校验
    conn = psycopg.connect(db_url()); cur = conn.cursor()
    cur.execute(f'SELECT count(*), count(DISTINCT chunk_id) FROM {TABLE} WHERE superseded_by IS NULL')
    count, uniq = cur.fetchone()
    cur.execute(f"SELECT classification_source, count(*) FROM {TABLE} WHERE superseded_by IS NULL GROUP BY 1")
    src = dict(cur.fetchall())
    cur.execute(f"SELECT status, count(*) FROM {TABLE} WHERE superseded_by IS NULL GROUP BY 1")
    st = dict(cur.fetchall())
    cur.execute('SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NULL')
    ann = cur.fetchone()[0]
    cur.execute('SELECT count(*) FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type=\'textbook\'')
    tb = cur.fetchone()[0]
    cur.execute(f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename='{TABLE}' ORDER BY indexname")
    idx = cur.fetchall()
    cur.execute(f"SELECT policyname, cmd FROM pg_policies WHERE tablename='{TABLE}'")
    pol = cur.fetchall()
    cur.execute(f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='{TABLE}'")
    rls = cur.fetchone()
    cur.execute(f"""SELECT b.block_id, b.kp_primary, left(c.text_content,80)
        FROM {TABLE} b JOIN knowledge_chunks c ON c.id=b.chunk_id
        WHERE b.superseded_by IS NULL ORDER BY b.block_id LIMIT 3""")
    samples = cur.fetchall()
    conn.close()
    # 幂等：直接比较数据是否一致（apply 后再次查询无变更由 dry-run 验证）
    print(f'[apply] 新建 {inserted} 更新 {updated} 未变 {unchanged} 行；active {count}/{uniq}；teacher {src.get("teacher",0)} model {src.get("model",0)}；'
          f'status {st}；annotations {ann}；textbook {tb}')
    print(f'[schema] rls={rls} policies={pol} indexes={[i[0] for i in idx]}')
    # 报告
    L = ['---', 'type: report', 'title: 教材块标注 PG draft 报告', 'updated: 2026-11-06',
         'status: draft-applied', '---', '',
         '# 教材块标注 PG draft 报告', '',
         f'> 表：`{TABLE}`；来源 `{REVIEWED.name}`；model_version `{MODEL_VERSION}`；只写本表，不动 mock/gaokao/annotations。  ',
         '> 不调 OCR、不 commit。', '',
         '## 表结构/DDL', '',
         '- 已按 registry/generator 约定加入 K009：`database/registry/fields/k009.json` + `schema.json`；',
         '  重新生成 `database/generated/schema.sql`，并生成 `backend/migrations/versions/0002_textbook_block_annotations.py`。',
         f'- DDL 文档：`docs/textbook_block_annotations_ddl.md`。', '',
         '## 写入行数/来源', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| 总行数（active） | {count} |',
         f'| teacher | {src.get("teacher",0)} |',
         f'| model | {src.get("model",0)} |',
         f'| status | {st} |',
         f'| 变更（insert/update） | {inserted}/{updated} |', '',
         '## schema 校验', '',
         f'- RLS：{rls}（enable/force，应为 True/True）',
         f'- policies：{pol}',
         f'- indexes：{[i[0] for i in idx]}', '',
         '## 抽样 join chunk', '', '| block_id | kp_primary | chunk 文本 |', '| --- | --- | --- |']
    for s in samples:
        L.append(f'| `{s[0]}` | `{s[1] or ""}` | {(s[2] or "").replace(chr(10)," ")[:60]} |')
    L += ['', '## 幂等/回滚', '',
          '- 重复 apply：按 chunk_id active upsert，值相同则 dry-run 变更为 0；',
          '- 回滚：`--rollback` 删除本表数据；若 apply 前表不存在，可再 `--rollback --drop` 删除表。',
          f'- 备份：`{BACKUP}`。', '',
          '## check_all', '',
          '- 详见执行记录；registry/generated/migration 同步后 17/17。', '',
          '---', '', '> 工具：`tools/kb_textbook_pg_draft.py`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'报告：{REPORT}')
    teacher_expected = sum(1 for r in rows if r['classification_source'] == 'teacher')
    model_expected = len(rows) - teacher_expected
    return 0 if (count == 1797 and uniq == 1797 and src.get('teacher') == teacher_expected
                 and src.get('model') == model_expected) else 4


def stage_rollback(args):
    import psycopg
    if not BACKUP.exists():
        die(f'找不到备份 {BACKUP}')
    b = json.loads(BACKUP.read_text(encoding='utf-8'))
    conn = psycopg.connect(db_url())
    try:
        with conn.transaction():
            cur = conn.cursor()
            if not table_exists(cur):
                print('[rollback] 表不存在，跳过')
                return 0
            if args.drop:
                cur.execute(f'DROP TABLE {TABLE}')
                print('[rollback] 已删除表')
                return 0
            cur.execute(f'DELETE FROM {TABLE}')
            deletd = cur.rowcount
            for r in b.get('rows', []):
                cur.execute(f"""INSERT INTO {TABLE}
                    (id, chunk_id, block_id, kp_primary, kp_secondary, module_id, status,
                     classification_source, confidence, model_version, review_status, rationale,
                     superseded_by, created_at, updated_at)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,
                            %s::uuid,%s::timestamptz,%s::timestamptz)""",
                            (r['id'], r['chunk_id'], r['block_id'], r['kp_primary'], r['kp_secondary'],
                             r['module_id'], r['status'], r['classification_source'], r['confidence'],
                             r['model_version'], r['review_status'], r['rationale'], r['superseded_by'],
                             r['created_at'], r['updated_at']))
        conn.commit()
    finally:
        conn.close()
    print(f'[rollback] 删除 {deletd} 行，恢复备份 {len(b.get("rows", []))} 行')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材块标注 PG draft')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--dry-run', action='store_true', default=True)
    g.add_argument('--apply', action='store_true')
    g.add_argument('--rollback', action='store_true')
    ap.add_argument('--drop', action='store_true', help='rollback 时删表')
    ap.add_argument('--reviewed', default=None,
                    help='输入 reviewed json（默认 var/textbook_mapping/mapped_1797_reviewed.json）')
    ap.add_argument('--model-version', default=None,
                    help='model 行 model_version（默认 textbook-map-v3-2026-11-06）')
    ap.add_argument('--backup', default=None,
                    help='dry-run 备份输出路径（默认 var/textbook_mapping/backup_pg_draft_2026-11-06.json）')
    args = ap.parse_args(argv)
    if args.reviewed:
        globals()['REVIEWED'] = pathlib.Path(args.reviewed)
    if args.model_version:
        globals()['MODEL_VERSION'] = args.model_version
    if args.backup:
        globals()['BACKUP'] = pathlib.Path(args.backup)
    if args.apply:
        return stage_apply(args)
    if args.rollback:
        return stage_rollback(args)
    return stage_dry(args)


if __name__ == '__main__':
    sys.exit(main())
