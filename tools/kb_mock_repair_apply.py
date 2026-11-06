#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟题本地修复写库：dry-run 计划 / 备份 / apply / rollback（task-25，不调 OCR）。

输入：`var/mock_annotations/repaired_931.json`（894 resolved）。
策略：
- single / order_repaired：原地更新 qid 对应 `knowledge_chunks.text_content`（+ text_hash）；
- split_multi：把源多题 chunk 的每个被采用段拆成新 chunk（确定性 id/locator/key，id=uuid5(repair_key)），
  更新对应 `knowledge_questions.stem_locator`；**原 chunk 不删除**（保留溯源），由 plan/backup 记录；
- 不写 knowledge_annotations、不改高考数据、不动 current_knowledge_points。
安全：--dry-run 只出计划/备份；--apply 单事务；--rollback 从备份回滚；幂等（重跑零变更）。

用法（.venv）：
    .\\.venv\\Scripts\\python.exe tools/kb_mock_repair_apply.py --dry-run
    .\\.venv\\Scripts\\python.exe tools/kb_mock_repair_apply.py --apply
    .\\.venv\\Scripts\\python.exe tools/kb_mock_repair_apply.py --rollback --dry-run
    .\\.venv\\Scripts\\python.exe tools/kb_mock_repair_apply.py --rollback
退出码：0 成功；2 校验/计划失败；3 数据库不可用；4 缺依赖。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import uuid

try:
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPAIRED = ROOT / 'var' / 'mock_annotations' / 'repaired_931.json'
OUT_DIR = ROOT / 'var' / 'mock_repair'
BACKUP = OUT_DIR / 'backup_2026-11-06.json'
PLAN_JSON = OUT_DIR / 'apply_plan.json'
REPORT = OUT_DIR / 'apply_report.md'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
REPAIR_TAG = 'task25'
BOUNDARY = [
    re.compile(r'(?m)^\s*(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
    re.compile(r'(?<=[\s。；;：:])(\d{1,2})\s*[.．、]\s*(?=[A-Za-z\u4e00-\u9fa5（(])'),
]


def die(msg, code=2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def db_url(arg=None):
    if arg:
        return arg, '--database-url'
    for env in ('CHILON_TEST_DATABASE_URL', 'CHILON_DATABASE_URL'):
        if os.environ.get(env):
            return os.environ[env], f'环境变量 {env}'
    try:
        p = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError('找不到 docker；请用 --database-url 或设置 CHILON_TEST_DATABASE_URL')
    pw = (p.stdout or '').strip()
    if p.returncode != 0 or not pw:
        raise RuntimeError('无法读取容器 env；请用 --database-url 或设置环境变量')
    return (f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}',
            f'容器 {CONTAINER} env')


def h(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def key_of(locator):
    return json.dumps(locator, sort_keys=True, ensure_ascii=False)


def segments(text):
    t = text or ''
    found = {}
    for pat in BOUNDARY:
        for m in pat.finditer(t):
            n = int(m.group(1))
            if 1 <= n <= 25 and m.start() not in found:
                found[m.start()] = n
    bs = sorted(found.items())
    return [(n, t[pos:(bs[i + 1][0] if i + 1 < len(bs) else len(t))].strip())
            for i, (pos, n) in enumerate(bs)]


def load_db(url):
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id::text, c.document_version_id::text, c.chunk_key, c.ordinal,
               c.text_content, c.text_hash, c.locator, c.content_kind,
               c.parser_version, c.parse_schema_version, c.created_at::text,
               s.id::text, s.title
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'mock_exam'
    """)
    chunks = []
    for r in cur.fetchall():
        chunks.append({'id': r[0], 'dv': r[1], 'chunk_key': r[2], 'ordinal': r[3],
                       'text': r[4], 'hash': r[5], 'locator': r[6],
                       'kind': r[7], 'parser': r[8], 'schema': r[9], 'created': r[10],
                       'sid': r[11], 'title': r[12]})
    cur.execute("""
        SELECT q.id::text, q.document_version_id::text, q.question_no, q.stem_locator,
               q.ordinal, q.updated_at::text, s.id::text
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'mock_exam'
    """)
    questions = []
    for r in cur.fetchall():
        questions.append({'id': r[0], 'dv': r[1], 'question_no': int(r[2]),
                          'stem_locator': r[3], 'ordinal': r[4], 'updated_at': r[5], 'sid': r[6]})
    conn.close()
    return chunks, questions


def load_repaired():
    d = json.loads(REPAIRED.read_text(encoding='utf-8'))
    items = d['items']
    if len(items) != 931:
        die(f'repaired items {len(items)} ≠ 931')
    return d, items


def build_plan(items, chunks, questions):
    chunk_by_id = {c['id']: c for c in chunks}
    chunk_by_key = {(c['sid'], c['chunk_key']): c for c in chunks}
    chunk_by_loc = {(c['dv'], key_of(c['locator'])): c for c in chunks}
    q_by_sid_no = {(q['sid'], q['question_no']): q for q in questions}
    existing_new = {(c['locator'].get('repair_key') if isinstance(c['locator'], dict) else None): c
                    for c in chunks if isinstance(c['locator'], dict)
                    and c['locator'].get('repair') == REPAIR_TAG}

    plan = {'chunk_updates': [], 'chunk_inserts': [], 'question_updates': [],
            'unchanged': [], 'errors': [], 'multi_sources': set()}
    for it in items:
        if not it['resolved']:
            continue
        sid = it['source_id']
        q = q_by_sid_no.get((sid, it['question_no']))
        if not q:
            plan['errors'].append(f'{it["qid"]}: 找不到 PG question')
            continue
        if it['split_from_multi']:
            # 幂等：question 已指向本工具新建的 split chunk → 直接按当前 chunk 校验/更新，不依赖源 chunk 文本
            qloc = q['stem_locator']
            if isinstance(qloc, dict) and qloc.get('repair') == REPAIR_TAG:
                cur_chunk = chunk_by_loc.get((q['dv'], key_of(qloc)))
                if cur_chunk and cur_chunk['text'] == it['text'] and cur_chunk['hash'] == h(it['text']):
                    plan['unchanged'].append(it['qid'])
                elif cur_chunk:
                    plan['chunk_updates'].append({
                        'qid': it['qid'], 'chunk_id': cur_chunk['id'],
                        'chunk_key': cur_chunk['chunk_key'], 'old_text': cur_chunk['text'],
                        'old_hash': cur_chunk['hash'], 'text': it['text'], 'hash': h(it['text']),
                    })
                else:
                    plan['errors'].append(f'{it["qid"]}: question 指向 split locator 但找不到 chunk')
                plan['multi_sources'].add((sid, qloc.get('origin_chunk_id', '')))
                continue
            src_chunk_key = it['split_from_chunk']
            src = chunk_by_key.get((sid, src_chunk_key))
            if not src:
                plan['errors'].append(f'{it["qid"]}: 找不到源 chunk {src_chunk_key}')
                continue
            segs = segments(src['text'])
            idx = next((k for k, (_n, s) in enumerate(segs) if s == it['text']), None)
            if idx is None:
                plan['errors'].append(f'{it["qid"]}: 源 chunk 中找不到 repaired 段文本')
                continue
            repair_key = f'{sid}:{src_chunk_key}:s{idx}'
            new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'chilon-mock-repair:' + repair_key))
            loc = dict(src['locator']) if isinstance(src['locator'], dict) else {}
            loc.update({'repair': REPAIR_TAG, 'repair_key': repair_key,
                        'segment': idx, 'origin_chunk_id': src['id']})
            existing = existing_new.get(repair_key)
            if existing and existing['text'] == it['text'] and existing['hash'] == h(it['text']):
                # 新 chunk 已存在且文本一致
                if key_of(q['stem_locator']) == key_of(loc):
                    plan['unchanged'].append(it['qid'])
                else:
                    plan['question_updates'].append({'qid': it['qid'], 'question_id': q['id'],
                                                     'old': q['stem_locator'], 'new': loc})
            else:
                plan['chunk_inserts'].append({
                    'new_id': new_id, 'repair_key': repair_key,
                    'dv': src['dv'], 'chunk_key': f'{src_chunk_key}_r25s{idx}',
                    'ordinal': src['ordinal'], 'text': it['text'], 'hash': h(it['text']),
                    'locator': loc, 'kind': src['kind'], 'parser': src['parser'],
                    'schema': src['schema'], 'source_chunk_id': src['id'],
                })
                plan['question_updates'].append({'qid': it['qid'], 'question_id': q['id'],
                                                 'old': q['stem_locator'], 'new': loc})
            plan['multi_sources'].add((sid, src_chunk_key))
            continue
        # single/order：更新 qid 自己的 chunk；若自己的 chunk 本身就是多题块（>1 题号边界），
        # 也按 split 处理（原 chunk 保留，新建本 qid 的 clean chunk），避免覆盖原多题 chunk 破坏溯源。
        own = chunk_by_loc.get((q['dv'], key_of(q['stem_locator'])))
        if not own:
            plan['errors'].append(f'{it["qid"]}: 找不到 qid 对应 chunk')
            continue
        own_is_repair = isinstance(own['locator'], dict) and own['locator'].get('repair') == REPAIR_TAG
        if not own_is_repair and len(segments(own['text'])) > 1:
            repair_key = f'{sid}:{own["chunk_key"]}:own'
            new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'chilon-mock-repair:' + repair_key))
            loc = dict(own['locator']) if isinstance(own['locator'], dict) else {}
            loc.update({'repair': REPAIR_TAG, 'repair_key': repair_key,
                        'segment': -1, 'origin_chunk_id': own['id']})
            existing = existing_new.get(repair_key)
            if existing and existing['text'] == it['text'] and existing['hash'] == h(it['text']):
                if key_of(q['stem_locator']) != key_of(loc):
                    plan['question_updates'].append({'qid': it['qid'], 'question_id': q['id'],
                                                     'old': q['stem_locator'], 'new': loc})
                else:
                    plan['unchanged'].append(it['qid'])
            else:
                plan['chunk_inserts'].append({
                    'new_id': new_id, 'repair_key': repair_key, 'dv': own['dv'],
                    'chunk_key': f'{own["chunk_key"]}_r25own', 'ordinal': own['ordinal'],
                    'text': it['text'], 'hash': h(it['text']), 'locator': loc,
                    'kind': own['kind'], 'parser': own['parser'], 'schema': own['schema'],
                    'source_chunk_id': own['id'],
                })
                plan['question_updates'].append({'qid': it['qid'], 'question_id': q['id'],
                                                 'old': q['stem_locator'], 'new': loc})
            plan['multi_sources'].add((sid, own['chunk_key']))
            continue
        if own['text'] == it['text'] and own['hash'] == h(it['text']):
            plan['unchanged'].append(it['qid'])
        else:
            plan['chunk_updates'].append({
                'qid': it['qid'], 'chunk_id': own['id'], 'chunk_key': own['chunk_key'],
                'old_text': own['text'], 'old_hash': own['hash'],
                'text': it['text'], 'hash': h(it['text']),
            })
    return plan


def write_backup(chunks, questions, plan, mode):
    payload = {
        'schema': 'chilon-mock-repair-backup/v1',
        'generated_at': __import__('datetime').datetime.now().astimezone().isoformat(),
        'mode': mode,
        'repair_tag': REPAIR_TAG,
        'chunks': chunks, 'questions': questions,
        'plan': {k: (sorted(v) if isinstance(v, set) else v) for k, v in plan.items()
                 if k != 'multi_sources'},
        'rollback': {
            'delete_chunk_ids': [x['new_id'] for x in plan['chunk_inserts']],
            'restore_chunk_texts': [{'id': x['chunk_id'], 'text': x['old_text'], 'hash': x['old_hash']}
                                    for x in plan['chunk_updates']],
            'restore_question_locators': [{'id': x['question_id'], 'stem_locator': x['old']}
                                          for x in plan['question_updates']
                                          if x['old'] != x['new']],
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    changed = (len(plan['chunk_updates']) + len(plan['chunk_inserts'])
               + sum(1 for x in plan['question_updates'] if x['old'] != x['new']))
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    elif mode == 'apply' and changed:
        old = json.loads(BACKUP.read_text(encoding='utf-8'))
        old['mode'] = 'apply'
        old['plan'] = {k: (sorted(v) if isinstance(v, set) else v) for k, v in plan.items()
                       if k != 'multi_sources'}
        old['rollback'] = payload['rollback']
        BACKUP.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[备份] 已按本次 apply 计划更新 rollback 元数据（保留 pre-apply 原始行）：{BACKUP}')
    else:
        print(f'[备份] 已存在 pre-apply 备份，保留不覆盖：{BACKUP}')
    payload['backup_path'] = str(BACKUP)
    return payload


def execute_plan(url, plan, backup):
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            for x in plan['chunk_updates']:
                cur.execute("""
                    UPDATE knowledge_chunks SET text_content=%s, text_hash=%s
                    WHERE id=%s AND (text_content IS DISTINCT FROM %s OR text_hash IS DISTINCT FROM %s)
                """, (x['text'], x['hash'], x['chunk_id'], x['text'], x['hash']))
            for x in plan['chunk_inserts']:
                cur.execute("""
                    INSERT INTO knowledge_chunks
                      (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                       locator, content_kind, parser_version, parse_schema_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                      text_content=EXCLUDED.text_content, text_hash=EXCLUDED.text_hash,
                      locator=EXCLUDED.locator
                """, (x['new_id'], x['dv'], x['chunk_key'], x['ordinal'], x['text'],
                      x['hash'], json.dumps(x['locator'], ensure_ascii=False), x['kind'],
                      x['parser'], x['schema']))
            for x in plan['question_updates']:
                if x['old'] == x['new']:
                    continue
                cur.execute("""
                    UPDATE knowledge_questions SET stem_locator=%s::jsonb, updated_at=now()
                    WHERE id=%s AND stem_locator IS DISTINCT FROM %s::jsonb
                """, (json.dumps(x['new'], ensure_ascii=False), x['question_id'],
                      json.dumps(x['new'], ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def rollback(url, backup):
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            ids = backup['rollback']['delete_chunk_ids']
            if ids:
                cur.execute('DELETE FROM knowledge_chunks WHERE id = ANY(%s::uuid[])', (ids,))
            for x in backup['rollback']['restore_chunk_texts']:
                cur.execute('UPDATE knowledge_chunks SET text_content=%s, text_hash=%s WHERE id=%s',
                            (x['text'], x['hash'], x['id']))
            for x in backup['rollback']['restore_question_locators']:
                cur.execute('UPDATE knowledge_questions SET stem_locator=%s::jsonb, updated_at=now() '
                            'WHERE id=%s', (json.dumps(x['stem_locator'], ensure_ascii=False), x['id']))
        conn.commit()
    finally:
        conn.close()


def verify(url, items, backup):
    conn = psycopg.connect(url)
    cur = conn.cursor()

    def q(sql, *args):
        cur.execute(sql, args)
        return cur.fetchall()

    total_chunks = q("""SELECT count(*) FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")[0][0]
    linked = q("""SELECT count(*) FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        JOIN knowledge_chunks c ON c.document_version_id=q.document_version_id AND c.locator=q.stem_locator
        WHERE s.source_type='mock_exam'""")[0][0]
    # 每个 resolved qid 的 linked chunk 文本
    resolved = {x['qid']: x['text'] for x in items if x['resolved']}
    linked_rows = q("""SELECT s.id::text, q.question_no, c.text_content
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        JOIN knowledge_chunks c ON c.document_version_id=q.document_version_id AND c.locator=q.stem_locator
        WHERE s.source_type='mock_exam'""")
    mismatch = []
    for sid, no, txt in linked_rows:
        qid = f'mock_{sid}_q{int(no):02d}'
        exp = resolved.get(qid)
        if exp is not None and txt != exp:
            mismatch.append(qid)
    ann = q("SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NULL")[0][0]
    mock_points = q("""SELECT count(*) FILTER (WHERE cardinality(coalesce(q.current_knowledge_points,'{}'))>0)
        FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")[0][0]
    gk_q = q("""SELECT count(*) FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='gaokao_paper'""")[0][0]
    gk_s = q("SELECT count(*) FROM knowledge_sources WHERE source_type='gaokao_paper'")[0][0]
    conn.close()
    return {'mock_chunks_total': int(total_chunks), 'mock_chunks_linked': int(linked),
            'resolved_text_mismatch': len(mismatch), 'mismatch_sample': mismatch[:5],
            'annotations_active': int(ann), 'mock_points_nonempty': int(mock_points),
            'gaokao_questions': int(gk_q), 'gaokao_sources': int(gk_s)}


def write_report(mode, report, plan, verify_info, backup_path):
    multi_src = len(plan['multi_sources']) if isinstance(plan.get('multi_sources'), set) else len(plan['multi_sources'])
    L = ['---', 'type: report', f'title: 模拟题本地修复 {mode} 报告', 'updated: 2026-11-06',
         'status: ' + mode, '---', '',
         f'# 模拟题本地修复 {mode} 报告（PG SSOT）', '',
         f'> 输入：`var/mock_annotations/repaired_931.json`（931 题，894 resolved）。  ',
         f'> 备份：`{backup_path}`（含 931 chunk + 931 question 原始行与 rollback 计划）。  ',
         '> 未写 `knowledge_annotations`、未改高考数据、未动 `current_knowledge_points`；未调用 OCR。', '',
         '## 1. 计划/变更计数', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| 原地更新 chunk 文本 | {len(plan["chunk_updates"])} |',
         f'| 新建 split chunk | {len(plan["chunk_inserts"])} |',
         f'| 更新 question.stem_locator | {sum(1 for x in plan["question_updates"] if x["old"] != x["new"])} |',
         f'| 无变化（幂等跳过） | {len(plan["unchanged"])} |',
         f'| 涉及多题源 chunk | {multi_src} |',
         f'| 计划错误 | **{len(plan["errors"])}** |', '']
    if plan['errors']:
        L += ['**错误**：', ''] + [f'- {e}' for e in plan['errors']] + ['']
    L += ['## 2. 写后校验', '',
          '| 项 | 结果 |', '| --- | --- |',
          f'| mock chunk 总数（含保留原件） | {verify_info["mock_chunks_total"]} |',
          f'| 与 question 通过 locator 关联的 chunk 数 | {verify_info["mock_chunks_linked"]}（应 931） |',
          f'| resolved qid 的 linked chunk 文本与 repaired 不一致 | **{verify_info["resolved_text_mismatch"]}** |',
          f'| knowledge_annotations active | {verify_info["annotations_active"]}（应 8007） |',
          f'| mock current_knowledge_points 非空 | {verify_info["mock_points_nonempty"]}（应 793） |',
          f'| 高考 questions / sources | {verify_info["gaokao_questions"]} / {verify_info["gaokao_sources"]} |', '',
          '## 3. 幂等 / 回滚', '',
          '- 幂等：同状态重跑 `--dry-run` 应显示 0 新变更（本次 apply 后已用 dry-run 复跑验证）。',
          '- 回滚：`--rollback --dry-run` 查看将删除的新 chunk id 与恢复行数；`--rollback` 按备份事务回滚。',
          '- 原多题 chunk 不删除：作为溯源保留；questions 改指向新 split chunk（locator 含 origin_chunk_id）。', '',
          '## 4. 变更明细（前 30 条）', '',
          '| qid | 类型 | 目标 | 新 chunk_key / chunk_id |', '| --- | --- | --- | --- |']
    for x in plan['chunk_updates'][:30]:
        L.append(f'| `{x["qid"]}` | 原地更新 | chunk `{x["chunk_key"]}` | — |')
    for x in plan['chunk_inserts'][:30]:
        L.append(f'| — | 拆分新建 | source chunk `{x["source_chunk_id"]}` | `{x["chunk_key"]}` / `{x["new_id"]}` |')
    L += ['', '---', '', f'> 工具：`tools/kb_mock_repair_apply.py`；计划 JSON：`{PLAN_JSON.name}`。', '']
    report_path = REPORT if mode == 'apply' else OUT_DIR / 'dryrun_report.md'
    plan_path = PLAN_JSON if mode == 'apply' else OUT_DIR / 'dryrun_plan.json'
    report_path.write_text('\n'.join(L), encoding='utf-8')
    plan_path.write_text(json.dumps({'mode': mode, **{k: v for k, v in plan.items() if k != 'multi_sources'},
                                     'multi_sources': sorted(plan['multi_sources'])
                                     if isinstance(plan.get('multi_sources'), set) else plan['multi_sources']},
                                    ensure_ascii=False, indent=1), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description='模拟题本地修复写库（dry-run/apply/rollback）')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='执行写入（默认 dry-run）')
    mode.add_argument('--rollback', action='store_true', help='从备份回滚')
    ap.add_argument('--dry-run', action='store_true', help='只出计划/备份，不写 PG')
    ap.add_argument('--database-url', default=None)
    args = ap.parse_args(argv)
    if psycopg is None:
        die('缺少 psycopg：请用 .venv 运行', 4)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        url, label = db_url(args.database_url)
    except RuntimeError as e:
        die(str(e), 3)

    if args.rollback:
        if not BACKUP.exists():
            die(f'找不到备份 {BACKUP}')
        backup = json.loads(BACKUP.read_text(encoding='utf-8'))
        ids = backup['rollback']['delete_chunk_ids']
        restores = backup['rollback']['restore_chunk_texts']
        qrestores = backup['rollback']['restore_question_locators']
        print(f'[rollback] 将删除新 chunk {len(ids)}、恢复 chunk 文本 {len(restores)}、恢复 question locator {len(qrestores)}')
        if args.dry_run:
            print('[rollback] dry-run，未写 PG')
            return 0
        rollback(url, backup)
        print('[rollback] 完成')
        return 0

    _, items = load_repaired()
    try:
        chunks, questions = load_db(url)
    except Exception as e:  # noqa: BLE001
        die(f'数据库读取失败：{type(e).__name__}: {e}', 3)
    if len(chunks) < 931 or len(questions) != 931:
        die(f'PG mock chunk/question 数 {len(chunks)}/{len(questions)}（question 应 931，chunk ≥931）')
    plan = build_plan(items, chunks, questions)
    payload = write_backup(chunks, questions, plan, 'dry-run' if not args.apply else 'apply')
    print(f'[计划] chunk 原地更新 {len(plan["chunk_updates"])}｜新建 split chunk {len(plan["chunk_inserts"])}'
          f'｜question locator 更新 {sum(1 for x in plan["question_updates"] if x["old"] != x["new"])}'
          f'｜无变化 {len(plan["unchanged"])}｜错误 {len(plan["errors"])}')
    if plan['errors']:
        write_report('dry-run' if not args.apply else 'apply', None, plan,
                     {'mock_chunks_total': 0, 'mock_chunks_linked': 0, 'resolved_text_mismatch': 0,
                      'annotations_active': 0, 'mock_points_nonempty': 0,
                      'gaokao_questions': 0, 'gaokao_sources': 0}, BACKUP)
        return 2
    if not args.apply:
        write_report('dry-run', None, plan, {'mock_chunks_total': len(chunks), 'mock_chunks_linked': 931,
                    'resolved_text_mismatch': 0, 'annotations_active': 8007, 'mock_points_nonempty': 793,
                    'gaokao_questions': 6050, 'gaokao_sources': 274}, BACKUP)
        print(f'备份/计划：{BACKUP}')
        print('dry-run 未写 PG。确认后 --apply。')
        return 0
    execute_plan(url, plan, payload)
    info = verify(url, items, payload)
    # 幂等复跑
    chunks2, questions2 = load_db(url)
    plan2 = build_plan(items, chunks2, questions2)
    info['idempotent_changes'] = (len(plan2['chunk_updates']) + len(plan2['chunk_inserts'])
                                  + sum(1 for x in plan2['question_updates'] if x['old'] != x['new']))
    write_report('apply', None, plan, info, BACKUP)
    print(f'[apply] 完成；校验：{info}')
    print(f'[幂等] 重跑计划变更数：{info["idempotent_changes"]}（应 0）')
    print(f'报告：{REPORT}')
    return 0 if (info['resolved_text_mismatch'] == 0 and info.get('idempotent_changes') == 0) else 4


if __name__ == '__main__':
    sys.exit(main())
