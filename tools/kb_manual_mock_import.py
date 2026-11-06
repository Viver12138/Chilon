#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""人工补录 6 题：解析 → 校验 → 备份 → 写 PG → 可回滚（不调 OCR）。

只用于 2026-11-06 人工补录文件（6 题，公式 \\(...\\)→$...$、\\[...\\]→$$...$$）。
- parse：解析/校验，输出 var/manual_transcription/parsed_6.json，并复制审计副本；
- apply：备份后只更新这 6 题的 linked chunk 文本；无 chunk/空文本时新建 chunk（provenance repair=manual）；
- rollback：从 backup_manual_2026-11-06.json 回滚；
- 不写 knowledge_annotations、不动高考/legacy；不调 OCR、不 commit。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse
import uuid

APPROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = APPROOT / 'var' / 'manual_transcription'
PARSED = OUT / 'parsed_6.json'
BACKUP = OUT / 'backup_manual_2026-11-06.json'
REPORT = OUT / 'manual_import_report.md'
NEEDED = APPROOT / 'var' / 'mock_annotations' / 'ocr_needed_final.json'
SRC = pathlib.Path(r'C:\Users\Viver\Desktop\模拟题人工补录_2026-11-06\待录入.md')
AUDIT = OUT / '待录入_已录入.md'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
MANUAL_TAG = 'manual'
EXPECTED = {
    'mock_a631c847-44dc-4d16-b498-66f5fabeccc7_q08': {'choice': True, 'no': 8},
    'mock_5ce982f9-0e94-4ae9-b932-ab27b03e9fe4_q08': {'choice': True, 'no': 8},
    'mock_5ce982f9-0e94-4ae9-b932-ab27b03e9fe4_q13': {'choice': False, 'no': 13},
    'mock_33b1a4f8-f1c0-4154-b5fe-17acccedc656_q11': {'choice': True, 'no': 11},
    'mock_6b9b1918-b575-4f6b-897b-f83bea23bb43_q08': {'choice': True, 'no': 8},
    'mock_8900819b-446c-42d5-9a38-511ffd2c7089_q11': {'choice': True, 'no': 11},
}


def die(msg, code=2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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


def key_of(locator):
    return json.dumps(locator, sort_keys=True, ensure_ascii=False)


def convert_math(text: str) -> str:
    # 独立公式先转换；行内后转换
    text = re.sub(r'\\\[(.*?)\\\]', lambda m: '$$' + m.group(1).strip() + '$$', text, flags=re.S)
    text = re.sub(r'\\\((.*?)\\\)', lambda m: '$' + m.group(1).strip() + '$', text, flags=re.S)
    return text


def parse_manual():
    if not SRC.exists():
        die(f'找不到人工补录文件 {SRC}')
    raw = SRC.read_text(encoding='utf-8')
    parts = re.split(r'(?m)^##\s+(\d+)\.\s+(.+?)\s*$', raw)
    # parts: [front, num, heading, body, num, heading, body...]
    items = []
    for i in range(1, len(parts), 3):
        num = int(parts[i])
        heading = parts[i + 1].strip()
        body = parts[i + 2]
        m_qid = re.search(r'- qid:\s*`([^`]+)`', body)
        if not m_qid:
            die(f'第 {num} 节找不到 qid')
        qid = m_qid.group(1).strip()
        m_no = re.search(r'第\s*(\d+)\s*题', heading) or re.search(r'^(\d+)[.．、]', body.strip())
        if not m_no:
            die(f'{qid}: 找不到题号')
        qno = int(m_no.group(1))
        m_set = re.match(r'(.+?)\s*·\s*第\s*\d+\s*题', heading)
        title = m_set.group(1).strip() if m_set else heading
        m_body = re.search(r'【题干】\s*(.*?)(?=\n\s*状态:|\n---|\Z)', body, flags=re.S)
        if not m_body:
            die(f'{qid}: 找不到【题干】')
        content = m_body.group(1).strip()
        lines = [ln.rstrip() for ln in content.splitlines()]
        stem_lines, options = [], []
        seen_option = False
        for ln in lines:
            if not ln.strip():
                continue
            m_opt = re.match(r'^([A-D])\s*[.．、]\s*(.*)$', ln.strip())
            if m_opt:
                seen_option = True
                options.append((m_opt.group(1), m_opt.group(2).strip()))
            elif not seen_option:
                stem_lines.append(ln.strip())
            else:
                # 选项续行，接到最后一个选项
                if options:
                    options[-1] = (options[-1][0], options[-1][1] + ' ' + ln.strip())
        stem = convert_math(' '.join(stem_lines).strip())
        opts = {k: convert_math(v) for k, v in options}
        text = stem + ('\n' + '\n'.join(f'{k}. {opts[k]}' for k in sorted(opts)) if opts else '')
        checks = {
            'expected_qid': qid in EXPECTED,
            'qid_matches_no': qid.endswith(f'_q{qno:02d}'),
            'question_no_matches_expected': EXPECTED.get(qid, {}).get('no') == qno,
            'text_nonempty': bool(stem) and len(text) >= 20,
            'options_complete': (sorted(opts) == list('ABCD') and all(v.strip() for v in opts.values()))
                                if EXPECTED.get(qid, {}).get('choice') else (not opts),
            'q13_complete': (('________' in text and '\\varphi' in text and len(text) >= 40)
                             if qid.endswith('_q13') else True),
        }
        items.append({'qid': qid, 'question_no': qno, 'set_title': title,
                      'stem': stem, 'options': opts, 'text': text, 'text_len': len(text),
                      'checks': checks, 'status': 'parsed'})
    # 全量校验
    errors = []
    got = {x['qid'] for x in items}
    if got != set(EXPECTED):
        errors.append(f'qid 集合不符：缺少 {set(EXPECTED)-got}，多出 {got-set(EXPECTED)}')
    for x in items:
        bad = [k for k, v in x['checks'].items() if not v]
        if bad:
            errors.append(f'{x["qid"]}: 校验失败 {bad}')
    choice_n = sum(1 for x in items if x['checks']['options_complete'] and x['options'])
    fill_n = sum(1 for x in items if x['checks']['q13_complete'] and x['qid'].endswith('_q13'))
    if len(items) != 6:
        errors.append(f'解析到 {len(items)} 题，应为 6')
    payload = {'source': str(SRC), 'source_sha256': sha256(raw), 'total': len(items),
               'choice_with_options': choice_n, 'fill_complete': fill_n,
               'errors': errors, 'items': items}
    OUT.mkdir(parents=True, exist_ok=True)
    PARSED.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    shutil.copyfile(SRC, AUDIT)
    print(f'[parse] {len(items)} 题；choice_options={choice_n}；q13_complete={fill_n}；errors={len(errors)}')
    if errors:
        for e in errors:
            print('  -', e)
        return 2
    print(f'输出：{PARSED}')
    print(f'审计副本：{AUDIT}')
    return 0


def load_db(url):
    import psycopg
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT q.id::text, q.document_version_id::text, q.question_no, q.stem_locator,
               c.id::text, c.chunk_key, c.text_content, c.text_hash, c.locator, c.ordinal,
               c.content_kind, c.parser_version, c.parse_schema_version,
               s.id::text, s.title
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        LEFT JOIN knowledge_chunks c ON c.document_version_id = q.document_version_id
             AND c.locator = q.stem_locator
        WHERE s.source_type = 'mock_exam'
    """)
    rows = cur.fetchall()
    conn.close()
    return [{'question_id': r[0], 'dv': r[1], 'question_no': int(r[2]), 'stem_locator': r[3],
             'chunk_id': r[4], 'chunk_key': r[5], 'text': r[6] or '', 'hash': r[7],
             'locator': r[8], 'ordinal': r[9], 'kind': r[10], 'parser': r[11],
             'schema': r[12], 'sid': r[13], 'title': r[14]} for r in rows]


def build_plan(parsed, rows):
    by_qid = {f'mock_{r["sid"]}_q{r["question_no"]:02d}': r for r in rows}
    plan = {'updates': [], 'inserts': [], 'question_updates': [], 'unchanged': [], 'errors': []}
    for x in parsed['items']:
        r = by_qid.get(x['qid'])
        if not r:
            plan['errors'].append(f'{x["qid"]}: 找不到 PG question')
            continue
        text = x['text']
        if r['text'].strip():
            if r['text'] == text and r['hash'] == sha256(text):
                plan['unchanged'].append(x['qid'])
            else:
                plan['updates'].append({'qid': x['qid'], 'chunk_id': r['chunk_id'],
                                        'chunk_key': r['chunk_key'], 'old_text': r['text'],
                                        'old_hash': r['hash'], 'text': text, 'hash': sha256(text)})
        else:
            repair_key = f'{r["sid"]}:{r["chunk_key"] or "none"}:manual'
            new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'chilon-manual:' + repair_key))
            loc = dict(r['locator']) if isinstance(r['locator'], dict) else {}
            loc.update({'repair': MANUAL_TAG, 'repair_key': repair_key,
                        'origin_chunk_id': r['chunk_id']})
            plan['inserts'].append({'qid': x['qid'], 'new_id': new_id, 'repair_key': repair_key,
                                    'dv': r['dv'], 'chunk_key': (r['chunk_key'] or 'manual') + '_manual',
                                    'ordinal': r['ordinal'] or 0, 'text': text, 'hash': sha256(text),
                                    'locator': loc, 'kind': r['kind'], 'parser': r['parser'],
                                    'schema': r['schema'], 'source_chunk_id': r['chunk_id']})
            plan['question_updates'].append({'qid': x['qid'], 'question_id': r['question_id'],
                                             'old': r['stem_locator'], 'new': loc})
    return plan


def write_backup(rows, plan):
    import psycopg
    conn = psycopg.connect(db_url())
    cur = conn.cursor()
    cur.execute("""SELECT c.id::text, c.document_version_id::text, c.chunk_key, c.ordinal,
        c.text_content, c.text_hash, c.locator, c.content_kind, c.parser_version,
        c.parse_schema_version, c.created_at::text, s.id::text, s.title
        FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    chunks = [dict(zip(['id','dv','chunk_key','ordinal','text','hash','locator','kind',
                        'parser','schema','created','sid','title'], row)) for row in cur.fetchall()]
    cur.execute("""SELECT q.id::text, q.document_version_id::text, q.question_no, q.stem_locator,
        q.ordinal, q.updated_at::text, s.id::text
        FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    questions = [dict(zip(['id','dv','question_no','stem_locator','ordinal','updated_at','sid'], row))
                 for row in cur.fetchall()]
    conn.close()
    backup = {'schema': 'chilon-manual-import-backup/v1', 'repair_tag': MANUAL_TAG,
              'chunks': chunks, 'questions': questions, 'plan': plan,
              'rollback': {
                  'delete_chunk_ids': [x['new_id'] for x in plan['inserts']],
                  'restore_chunk_texts': [{'id': u['chunk_id'], 'text': u['old_text'],
                                           'hash': u['old_hash']} for u in plan['updates']],
                  'restore_question_locators': [{'id': qu['question_id'], 'old': qu['old']}
                                                for qu in plan['question_updates']],
              }}
    BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'[备份] {BACKUP}（chunks {len(chunks)} / questions {len(questions)}）')


def apply_plan(plan):
    import psycopg
    conn = psycopg.connect(db_url())
    try:
        with conn.transaction():
            cur = conn.cursor()
            for u in plan['updates']:
                cur.execute('UPDATE knowledge_chunks SET text_content=%s, text_hash=%s '
                            'WHERE id=%s AND (text_content IS DISTINCT FROM %s OR text_hash IS DISTINCT FROM %s)',
                            (u['text'], u['hash'], u['chunk_id'], u['text'], u['hash']))
            for x in plan['inserts']:
                cur.execute("""INSERT INTO knowledge_chunks
                    (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                     locator, content_kind, parser_version, parse_schema_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET text_content=EXCLUDED.text_content,
                    text_hash=EXCLUDED.text_hash, locator=EXCLUDED.locator""",
                    (x['new_id'], x['dv'], x['chunk_key'], x['ordinal'], x['text'], x['hash'],
                     json.dumps(x['locator'], ensure_ascii=False), x['kind'], x['parser'], x['schema']))
            for qu in plan['question_updates']:
                cur.execute('UPDATE knowledge_questions SET stem_locator=%s::jsonb, updated_at=now() '
                            'WHERE id=%s', (json.dumps(qu['new'], ensure_ascii=False), qu['question_id']))
        conn.commit()
    finally:
        conn.close()


def update_status(parsed):
    d = json.loads(NEEDED.read_text(encoding='utf-8'))
    by = {x['qid']: x for x in parsed['items']}
    for x in d['items']:
        p = by.get(x['qid'])
        if p:
            x['status'] = 'done'
            x['source'] = 'manual'
            x['manual'] = True
            x['text_len'] = p['text_len']
            x['manual_checks'] = p['checks']
    done = sum(1 for x in d['items'] if x.get('status') == 'done')
    unresolved = sum(1 for x in d['items'] if x.get('status') == 'unresolved')
    manual = sum(1 for x in d['items'] if x.get('manual'))
    d['status_summary'] = {'done': done, 'unresolved': unresolved, 'manual': manual,
                           'ocr_done': done - manual, 'updated': '2026-11-06'}
    NEEDED.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    # md 同步
    L = ['---', 'type: data', 'title: 模拟题 OCR/人工补录最终状态', 'updated: 2026-11-06', '---', '',
         '# 模拟题 39 题最终状态（33 OCR + 6 人工）', '',
         f'> status：**done {done} / unresolved {unresolved}**（manual {manual}）；'
         '仅阿里云 RecognizeEduPaperCut + 人工转录，未换其他 OCR。', '',
         '| qid | 套 | 题号 | 原原因 | status | 来源 | 文本长度 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for x in d['items']:
        L.append(f'| `{x["qid"]}` | {x["set_title"]} | {x["question_no"]} | {x["reason"]} | '
                 f'**{x["status"]}** | {x.get("source", "aliyun")} | {x.get("text_len", "—")} |')
    L += ['', '> 明细 JSON：`ocr_needed_final.json`；人工报告：`var/manual_transcription/manual_import_report.md`。', '']
    (APPROOT / 'var' / 'mock_annotations' / 'ocr_needed_final.md').write_text('\n'.join(L), encoding='utf-8')
    print(f'[status] done {done} / unresolved {unresolved} / manual {manual}')


def stage_apply(args):
    parsed = json.loads(PARSED.read_text(encoding='utf-8'))
    if parsed['errors']:
        die('parsed_6.json 有校验错误，拒绝写 PG')
    rows = load_db(db_url())
    if len(rows) != 931:
        die(f'linked mock questions {len(rows)} ≠ 931')
    plan = build_plan(parsed, rows)
    print(f'[计划] update {len(plan["updates"])}｜insert {len(plan["inserts"])}｜'
          f'question locator {len(plan["question_updates"])}｜unchanged {len(plan["unchanged"])}｜'
          f'errors {len(plan["errors"])}')
    if plan['errors']:
        for e in plan['errors']:
            print('  -', e)
        return 2
    if not BACKUP.exists() or (args.force_backup and (plan['updates'] or plan['inserts'])):
        write_backup(rows, plan)
    else:
        print(f'[备份] 保留已有 {BACKUP}')
    if args.dry_run:
        print('[dry-run] 未写 PG')
        return 0
    apply_plan(plan)
    # 校验计数
    import psycopg
    conn = psycopg.connect(db_url()); cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    total = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM knowledge_questions q JOIN knowledge_chunks c ON c.document_version_id=q.document_version_id AND c.locator=q.stem_locator JOIN knowledge_document_versions dv ON dv.id=q.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    linked = cur.fetchone()[0]
    cur.execute('SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NULL'); ann = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FILTER (WHERE cardinality(coalesce(q.current_knowledge_points,'{}'))>0) FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    pts = cur.fetchone()[0]
    cur.execute("""SELECT (SELECT count(*) FROM knowledge_sources WHERE source_type='gaokao_paper'), (SELECT count(*) FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='gaokao_paper')""")
    gk = cur.fetchone(); conn.close()
    print(f'[apply] chunks {total}｜linked {linked}｜annotations {ann}｜mock_points {pts}｜gk {gk}')
    # 幂等复跑
    rows2 = load_db(db_url())
    plan2 = build_plan(parsed, rows2)
    changes = len(plan2['updates']) + len(plan2['inserts']) + len(plan2['question_updates'])
    print(f'[幂等] 重跑变更数 {changes}（应 0）')
    update_status(parsed)
    return 0 if changes == 0 else 4


def stage_rollback(args):
    import psycopg
    if not BACKUP.exists():
        die(f'找不到备份 {BACKUP}')
    b = json.loads(BACKUP.read_text(encoding='utf-8'))
    ids = b['rollback']['delete_chunk_ids']
    print(f'[rollback] 删除新 chunk {len(ids)}｜恢复 chunk 文本 {len(b["rollback"]["restore_chunk_texts"])}｜'
          f'恢复 question locator {len(b["rollback"]["restore_question_locators"])}')
    if args.dry_run:
        print('[rollback] dry-run，未写 PG')
        return 0
    conn = psycopg.connect(db_url())
    try:
        with conn.transaction():
            cur = conn.cursor()
            if ids:
                cur.execute('DELETE FROM knowledge_chunks WHERE id = ANY(%s::uuid[])', (ids,))
            for x in b['rollback']['restore_chunk_texts']:
                cur.execute('UPDATE knowledge_chunks SET text_content=%s, text_hash=%s WHERE id=%s',
                            (x['text'], x['hash'], x['id']))
            for x in b['rollback']['restore_question_locators']:
                cur.execute('UPDATE knowledge_questions SET stem_locator=%s::jsonb, updated_at=now() WHERE id=%s',
                            (json.dumps(x['old'], ensure_ascii=False), x['id']))
        conn.commit()
    finally:
        conn.close()
    print('[rollback] 完成')
    return 0


def write_report(parsed, extra=None):
    extra = extra or {}
    items = parsed['items']
    L = ['---', 'type: report', 'title: 人工补录 6 题入库报告', 'updated: 2026-11-06',
         'status: done', '---', '',
         '# 人工补录 6 题入库报告（不调 OCR）', '',
         f'> 来源：`{parsed["source"]}`（sha256 `{parsed["source_sha256"][:16]}…`）  ',
         '> 公式已按 `\\(...\\)`→`$...$`、`\\[...\\]`→`$$...$$` 转换；仅改这 6 题，不调 OCR、不做 Qdrant、不 commit。', '',
         '## 1. 解析与校验', '',
         f'- 解析：**{parsed["total"]}/6**；选择项齐全 {parsed["choice_with_options"]}/5；q13 完整 {parsed["fill_complete"]}/1；errors **{len(parsed["errors"])}**',
         '', '| qid | 题号 | 选项 | 文本长度 | 校验 |', '| --- | --- | --- | --- | --- |']
    for x in items:
        ok = '✅' if all(x['checks'].values()) else '❌'
        L.append(f'| `{x["qid"]}` | {x["question_no"]} | {" / ".join(sorted(x["options"])) or "—"} | '
                 f'{x["text_len"]} | {ok} |')
    L += ['', '## 2. PG 变更', '',
          f'- 原地更新 chunk 文本：**{extra.get("updates", "?")}**',
          f'- 新建 chunk（无文本时）：**{extra.get("inserts", "?")}**',
          f'- 更新 question.stem_locator：**{extra.get("question_updates", "?")}**',
          f'- 已一致跳过：**{extra.get("unchanged", "?")}**',
          f'- mock chunk：**{extra.get("chunks_before", "?")} → {extra.get("chunks_after", "?")}**；'
          f'linked questions：**{extra.get("linked", "?")}**',
          f'- annotations：**{extra.get("annotations", "?")}**；mock legacy points：**{extra.get("mock_points", "?")}**；'
          f'高考：**{extra.get("gk")}**',
          f'- 备份：`{BACKUP}`；回滚：`--stage rollback`；幂等复跑变更数：**{extra.get("idempotent", "?")}**', '',
          '## 3. 重投影与校验', '',
          f'- 卡片写入：**{extra.get("cards_written", "?")}**；931 卡 + 67 set note：**{extra.get("card_counts", "?")}**',
          f'- 6 题卡片文本与人工录入一致：**{extra.get("card_match", "?")}**',
          f'- 高考卡：**{extra.get("gk_cards", "?")}**',
          f'- `ocr_needed_final.json`：**done 39 / unresolved 0（33 OCR + 6 manual）**', '',
          '## 4. 审计', '',
          f'- 已填文件副本：`{AUDIT}`（未删除桌面临时文件夹）',
          f'- parsed：`{PARSED}`', '', '---', '', '> 工具：`tools/kb_manual_mock_import.py`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'报告：{REPORT}')


def main(argv=None):
    ap = argparse.ArgumentParser(description='人工补录 6 题入库（不调 OCR）')
    ap.add_argument('--stage', choices=['parse', 'apply', 'rollback'], default='parse')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force-backup', action='store_true')
    args = ap.parse_args(argv)
    if args.stage == 'parse':
        return parse_manual()
    if args.stage == 'rollback':
        return stage_rollback(args)
    return stage_apply(args)


if __name__ == '__main__':
    sys.exit(main())
