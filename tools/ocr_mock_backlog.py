#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟题 backlog 39 题：阿里云「试卷切题」批量 OCR + 回填（仅 RecognizeEduPaperCut）。

阶段：
  --stage ocr     （默认）按 (PDF, page) 调 RecognizeEduPaperCut(scan)，必要时 ±1 页 scan
                  或同服务 photo 再试；原始 JSON 存 var/ocr_mock/raw/，输出 recovered_39.json。
  --stage apply   备份后把 recovered 文本写回 PG（只动 39 题；单题更新/整套缺段新建 chunk/
                  语义残缺更新），幂等、可回滚；不改 annotations/高考/legacy。
  --stage rollback 从 var/ocr_mock/backup_ocr_2026-11-06.json 回滚。

约束：只调用阿里云试卷切题接口；不打印密钥；不调用其他 OCR；不写 Qdrant。
用法（.venv）：
    .\\.venv\\Scripts\\python.exe tools/ocr_mock_backlog.py --stage ocr [--only-pdf 天津] [--no-photo]
    .\\.venv\\Scripts\\python.exe tools/ocr_mock_backlog.py --stage apply
    .\\.venv\\Scripts\\python.exe tools/ocr_mock_backlog.py --stage rollback [--dry-run]
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
import time
import urllib.parse
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
OUT = ROOT / 'var' / 'ocr_mock'
RAW = OUT / 'raw'
NEEDED = ROOT / 'var' / 'mock_annotations' / 'ocr_needed_final.json'
RECOVERED = OUT / 'recovered_39.json'
BACKUP = OUT / 'backup_ocr_2026-11-06.json'
REPORT = OUT / 'ocr_batch_report.md'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
OCR_TAG = 'ocr39_task28'
START_NUM = re.compile(r'^\s*(?:[（(]\s*(\d{1,2})\s*[)）]|(\d{1,2})\s*[.．、])')
OPTION_START = re.compile(r'^\s*(?:[（(]\s*[A-D]\s*[)）]|[A-D]\s*[.．、])')
MATH_TOKEN = re.compile(r'\$\$[^$]*\$\$|\$[^$]*\$')
SECTION_HEAD = re.compile(r'^\s*[一二三四五六七八九十]+、[^（(\n]{0,40}(?=[（(]\s*\d{1,2}\s*[)）])')
ANY_NUM = re.compile(r'(?:^|[。；：:、\s])[（(]?(\d{1,2})[)）.．、]\s*(?=\S)')
MATH_LEAD = re.compile(r'^\s*\$\$\s*(\d{1,2})\s*[.．、]')
MATH_OPTION = re.compile(r'^\s*\$\$[^$]*\\left\(\s*[A-D]\s*\\right\)')
QUESTION_HINT = re.compile(r'求|则|已知|若|设|函数|下列|正确|方程|集合|概率|数列|向量|曲线|体积|面积|解|证')


def is_fragment(stem: str) -> bool:
    s = (stem or '').strip()
    if OPTION_START.match(s):
        return True
    if re.match(r'^\s*(?:\$\$[^$]*\$\$\s*)+[（(]\s*[A-D]', s):
        return True
    plain = MATH_TOKEN.sub('', s)
    if re.match(r'^\s*(?:[（(]\s*[A-D]\s*[)）]|[A-D]\s*[.．、])', plain):
        return True
    if len(s) < 100 and len(re.findall(r'[（(]\s*[A-D]\s*[)）]', plain)) >= 2 and not QUESTION_HINT.search(s):
        return True
    return False


def die(msg, code=2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]


def db_url():
    if os.environ.get('CHILON_TEST_DATABASE_URL'):
        return os.environ['CHILON_TEST_DATABASE_URL'], '环境变量 CHILON_TEST_DATABASE_URL'
    if os.environ.get('CHILON_DATABASE_URL'):
        return os.environ['CHILON_DATABASE_URL'], '环境变量 CHILON_DATABASE_URL'
    pw = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', 'POSTGRES_PASSWORD'],
                        capture_output=True, text=True).stdout.strip()
    if not pw:
        raise RuntimeError('无法读取容器 env')
    return (f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}',
            f'容器 {CONTAINER} env')


def load_creds():
    from app import settings as config
    cfg = config.load()
    kid = os.environ.get('CHILON_OCR_ALIYUN_KEY_ID') or cfg.ocr_aliyun_key_id
    sec = os.environ.get('CHILON_OCR_ALIYUN_KEY_SECRET') or cfg.ocr_aliyun_key_secret
    if not kid or not sec:
        raise RuntimeError('缺少阿里云 OCR credentials')
    return kid, sec


def parse_candidates(payload, page, raw_file):
    """把一次 RecognizeEduPaperCut 响应解析为候选题目列表。"""
    from app.services import aliyun_ocr
    data = aliyun_ocr.decode_data(payload)
    try:
        qs = aliyun_ocr.extract_questions(data, page=page)
    except aliyun_ocr.ShapeUnknown as exc:
        return [], str(exc)
    out = []
    for idx, q in enumerate(qs):
        stem = (q.stem or '').strip()
        if not stem:
            continue
        sec = SECTION_HEAD.match(stem)
        if sec:
            stem = stem[sec.end():].strip()
        if not stem:
            continue
        num = None
        id_num = None
        if q.number:
            m = re.search(r'\d{1,2}', str(q.number))
            if m:
                id_num = int(m.group(0))
                num = id_num
        lead = START_NUM.match(stem)
        lead_num = None
        if lead:
            lead_num = int(lead.group(1) or lead.group(2))
        if lead_num is None:
            ml = MATH_LEAD.match(stem)
            if ml:
                lead_num = int(ml.group(1))
        # ids 里的号码优先；但若 stem 明显是选项碎片（以 (A)/A. 开头）则视为碎片
        # ids 有编号但 stem 没有行首题号：若像选项/过短/无题干特征则视为残片；否则（如“若……”开头）仍可用
        is_option = is_fragment(stem) or bool(MATH_OPTION.match(stem))
        if id_num is not None and lead_num is None and not is_option:
            if len(stem) < 60 or not QUESTION_HINT.search(stem):
                is_option = True
        if num is None:
            num = lead_num
        if num is None and not is_option and QUESTION_HINT.search(stem):
            m = ANY_NUM.search(stem[:120])
            if m:
                num = int(m.group(1))
        if num is not None and not (1 <= num <= 30):
            num = lead_num
        text = '\n'.join(x for x in [stem, ' '.join(q.options or [])] if x)
        if num is not None and len(text) > 20:
            tail = text[4:]
            for mm in re.finditer(r'(?:^|[\n。；;.．])\s*[（(]?(\d{1,2})[)）.．、]\s*(?=\S)', tail):
                nxt = int(mm.group(1))
                if num < nxt <= num + 5:
                    cut = 4 + mm.start()
                    text = text[:cut].rstrip()
                    stem = stem[:cut].rstrip()
                    break
        out.append({
            'raw_file': raw_file, 'index': idx, 'page': page, 'num': num,
            'lead_num': lead_num, 'is_option': is_option,
            'stem': stem, 'options': list(q.options or []), 'answer': q.answer,
            'text': text,
        })
    return out, None


def ocr_call(pdf_path, page, image_type, purpose, state, no_photo=False):
    """带 resume/重试的单页调用；返回 (candidates, call_record, error)。"""
    key = f'{sha1(pdf_path.name)}_p{page:02d}_{image_type}'
    raw_file = RAW / f'{key}.json'
    rec = state['calls'].get(key)
    if rec and rec.get('status') == 'ok' and raw_file.exists():
        payload = json.loads(raw_file.read_text(encoding='utf-8'))
        cands, err = parse_candidates(payload, page, raw_file.name)
        return cands, {**rec, 'resumed': True}, err
    if no_photo and image_type == 'photo':
        return [], None, 'photo disabled'
    from app.services import ocr as ocr_service
    from app.services import aliyun_ocr
    pages = state['pages'][pdf_path.name]
    if page < 1 or page > len(pages):
        return [], None, f'page {page} out of range 1..{len(pages)}'
    provider = ocr_service.AliyunPaperCutProvider(
        state['key_id'], state['key_secret'], image_type=image_type, subject='Math')
    params = {'CutType': 'question', 'ImageType': image_type,
              'Subject': 'Math', 'OutputOricoord': 'false'}
    last = None
    for attempt in range(1, 3):
        t0 = time.time()
        try:
            payload = provider._call(pages[page - 1], params, page)
            RAW.mkdir(parents=True, exist_ok=True)
            raw_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
            cands, err = parse_candidates(payload, page, raw_file.name)
            rec = {'pdf': pdf_path.name, 'page': page, 'image_type': image_type,
                   'purpose': purpose, 'attempt': attempt, 'status': 'ok',
                   'seconds': round(time.time() - t0, 2), 'bytes': len(pages[page - 1]),
                   'raw_file': raw_file.name, 'candidates': len(cands)}
            state['calls'][key] = rec
            return cands, rec, err
        except Exception as e:  # noqa: BLE001
            last = e
            state['calls'][key] = {'pdf': pdf_path.name, 'page': page,
                                   'image_type': image_type, 'purpose': purpose,
                                   'attempt': attempt, 'status': 'failed',
                                   'seconds': round(time.time() - t0, 2),
                                   'error': f'{type(e).__name__}: {e}'[:300],
                                   'raw_file': None, 'candidates': 0}
            time.sleep(1.0 * attempt)
    return [], state['calls'][key], f'{type(last).__name__}: {last}'


def score_candidate(c, target, target_page, used):
    if c['is_option'] or c['num'] is None:
        return None
    if len((c.get('stem') or '').strip()) < 25:
        return None
    if c['raw_file'] + ':' + str(c['index']) in used:
        return None
    expected = target.get('expected') or []
    if c['num'] not in expected and c['lead_num'] not in expected:
        return None
    page_score = 2 if c['page'] == target_page else (1 if abs(c['page'] - target_page) <= 1 else 0)
    num_score = 3 if c['num'] == target.get('assigned') else (2 if c['num'] == target['question_no'] else 1)
    len_score = 1 if len(c['stem']) >= 30 else 0
    return num_score * 10 + page_score * 3 + len_score


def assign(targets, candidates, used):
    """贪心匹配；同套内每个候选仅用一次。"""
    recovered = {}
    pending = [t for t in targets if t['qid'] not in recovered]
    # 每轮选全局最高分
    while pending:
        best = None
        for t in pending:
            for c in candidates:
                s = score_candidate(c, t, t['page'], used)
                if s is None:
                    continue
                if best is None or s > best[0]:
                    best = (s, t, c)
        if not best:
            break
        _s, t, c = best
        used.add(c['raw_file'] + ':' + str(c['index']))
        recovered[t['qid']] = c
        pending.remove(t)
    return recovered


def stage_ocr(args):
    from app.services import ocr as ocr_service
    needed = json.loads(NEEDED.read_text(encoding='utf-8'))['items']
    repaired = {x['qid']: x for x in json.loads(
        (ROOT / 'var' / 'mock_annotations' / 'repaired_931.json').read_text(encoding='utf-8'))['items']}
    if args.only_pdf:
        needed = [x for x in needed if args.only_pdf in x['set_title'] or args.only_pdf in x['source_pdf']]
        if not needed:
            die(f'--only-pdf {args.only_pdf!r} 没有匹配项')
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    kid, sec = load_creds()
    state = {'key_id': kid, 'key_secret': sec, 'pages': {}, 'calls': {}}
    # 恢复已有 calls 元数据（若有）
    if (OUT / 'calls.json').exists():
        try:
            old = json.loads((OUT / 'calls.json').read_text(encoding='utf-8'))
            state['calls'].update(old)
        except Exception:  # noqa: BLE001
            pass
    by_pdf = collections.OrderedDict()
    for x in needed:
        by_pdf.setdefault(x['source_pdf'], []).append(x)
    recovered, unresolved, extras = {}, [], []
    t_start = time.time()
    for pdf_str, items in by_pdf.items():
        pdf_path = pathlib.Path(pdf_str)
        if not pdf_path.exists():
            for x in items:
                unresolved.append((x, 'source_pdf 不存在'))
            continue
        print(f'[PDF] {pdf_path.name}（{len(items)} 题）', flush=True)
        pages = ocr_service.render_pages(pdf_path.read_bytes())
        state['pages'][pdf_path.name] = pages
        print(f'       pages={len(pages)}', flush=True)
        # 该套目标
        targets = []
        for x in items:
            assigned = repaired.get(x['qid'], {}).get('assigned_visible_no')
            exp = {x['question_no']}
            if assigned:
                exp.add(assigned)
            targets.append({'qid': x['qid'], 'item': x, 'question_no': x['question_no'],
                            'assigned': assigned, 'expected': exp, 'page': x['page']})
        # 目标页
        primary = sorted({t['page'] for t in targets if t['page']})
        candidates, used = [], set()
        for p in primary:
            cands, rec, err = ocr_call(pdf_path, p, 'scan', 'primary', state, args.no_photo)
            candidates.extend(cands)
            if err:
                print(f'       [warn] p{p} scan: {err}', flush=True)
        got = assign(targets, candidates, used)
        recovered.update(got)
        # ±1 页补救
        extra_pages = sorted({p for t in targets if t['qid'] not in recovered
                              for p in (t['page'] - 1, t['page'] + 1)})
        for p in extra_pages:
            if p < 1 or p > len(pages) or p in primary:
                continue
            cands, rec, err = ocr_call(pdf_path, p, 'scan', 'extra-page', state, args.no_photo)
            candidates.extend(cands)
            extras.append({'pdf': pdf_path.name, 'page': p, 'type': 'scan', 'purpose': 'extra-page'})
            got = assign(targets, candidates, used)
            recovered.update(got)
        # 同服务 photo 再试（未恢复目标自己的页 ±1 页；仍只调用 RecognizeEduPaperCut）
        if not args.no_photo:
            photo_pages = sorted({p for t in targets if t['qid'] not in recovered
                                  for p in (t['page'] - 1, t['page'], t['page'] + 1)
                                  if 1 <= p <= len(pages)})
            for p in photo_pages:
                cands, rec, err = ocr_call(pdf_path, p, 'photo', 'photo-fallback', state, False)
                candidates.extend(cands)
                extras.append({'pdf': pdf_path.name, 'page': p, 'type': 'photo', 'purpose': 'photo-fallback'})
                got = assign(targets, candidates, used)
                recovered.update(got)
        for t in targets:
            if t['qid'] not in recovered:
                unresolved.append((t['item'], '阿里云 paper-cut 未返回匹配题号'))

    elapsed = round(time.time() - t_start, 1)
    # recovered_39.json
    rows = []
    for x in needed:
        qid = x['qid']
        c = recovered.get(qid)
        row = dict(x)
        if c:
            text = c['text'].strip()
            if c.get('answer'):
                text = text + '\n【答案】' + c['answer'].strip() + '（来源：阿里云试卷切题返回）'
            row.update({'status': 'recovered', 'text': text, 'text_len': len(text),
                        'ocr_num': c['num'], 'ocr_page': c['page'], 'ocr_raw': c['raw_file'],
                        'already_existing': False})
        else:
            row.update({'status': 'unresolved', 'text': None, 'text_len': 0,
                        'ocr_num': None, 'ocr_page': None, 'ocr_raw': None})
        rows.append(row)
    payload = {'total': len(rows), 'recovered': sum(1 for r in rows if r['status'] == 'recovered'),
               'unresolved': sum(1 for r in rows if r['status'] == 'unresolved'),
               'calls': len([1 for v in state['calls'].values() if not v.get('resumed')]),
               'calls_total_records': len(state['calls']), 'elapsed_sec': elapsed,
               'items': rows}
    RECOVERED.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'calls.json').write_text(json.dumps(state['calls'], ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'unresolved.json').write_text(json.dumps(
        [{'qid': x['qid'], 'set': x['set_title'], 'qno': x['question_no'],
          'reason': reason} for x, reason in unresolved], ensure_ascii=False, indent=1), encoding='utf-8')
    # OCR 阶段报告（apply 后会重写完整报告）
    L = ['---', 'type: report', 'title: 阿里云试卷切题 OCR（39 题）阶段报告',
         'updated: 2026-11-06', 'status: ocr', '---', '',
         '# 阿里云「试卷切题」批量 OCR（39 题）', '',
         '> 只调用 `RecognizeEduPaperCut`；未调用任何其他 OCR；未写 PG/卡片。', '',
         '## 统计', '',
         f'- 目标：{len(rows)} 题（{len(by_pdf)} 份 PDF）',
         f'- recovered：**{payload["recovered"]}**｜unresolved：**{payload["unresolved"]}**',
         f'- API 调用（非 resume）：**{payload["calls"]}**（记录 {payload["calls_total_records"]} 条，含重试/补页/photo）',
         f'- 额外页：{len(extras)}（±1 页/photo；明细见 calls.json）',
         f'- 耗时：{elapsed}s', '',
         '## recovered 清单', '',
         '| qid | 套 | 题号 | OCR 页 | OCR 号 | 文本长度 |', '| --- | --- | --- | --- | --- | --- |']
    for r in rows:
        if r['status'] == 'recovered':
            L.append(f'| `{r["qid"]}` | {r["set_title"]} | {r["question_no"]} | {r["ocr_page"]} | '
                     f'{r["ocr_num"]} | {r["text_len"]} |')
    L += ['', '## unresolved', '', '| qid | 套 | 题号 | 原因 |', '| --- | --- | --- | --- |']
    for x, reason in unresolved:
        L.append(f'| `{x["qid"]}` | {x["set_title"]} | {x["question_no"]} | {reason} |')
    L += ['', '---', '', '> 原始 JSON：`var/ocr_mock/raw/`；调用记录：`calls.json`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[OCR] recovered {payload["recovered"]}/{len(rows)}｜unresolved {payload["unresolved"]}｜'
          f'calls {payload["calls"]}｜耗时 {elapsed}s')
    print(f'输出：{RECOVERED}')
    return 0


# ── apply / rollback ─────────────────────────────────────────────────────────
def h(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def key_of(locator):
    return json.dumps(locator, sort_keys=True, ensure_ascii=False)


def load_db(url):
    import psycopg
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id::text, c.document_version_id::text, c.chunk_key, c.ordinal,
               c.text_content, c.text_hash, c.locator, c.content_kind,
               c.parser_version, c.parse_schema_version, s.id::text, s.title, q.id::text,
               q.question_no, q.stem_locator, q.updated_at::text
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        JOIN knowledge_questions q ON q.document_version_id=c.document_version_id
             AND q.stem_locator=c.locator
        WHERE s.source_type='mock_exam'
    """)
    rows = cur.fetchall()
    conn.close()
    return [{'chunk_id': r[0], 'dv': r[1], 'chunk_key': r[2], 'ordinal': r[3],
             'text': r[4], 'hash': r[5], 'locator': r[6], 'kind': r[7],
             'parser': r[8], 'schema': r[9], 'sid': r[10], 'title': r[11],
             'question_id': r[12], 'question_no': int(r[13]), 'stem_locator': r[14],
             'updated_at': r[15]} for r in rows]


def stage_apply(args):
    import psycopg
    rec = json.loads(RECOVERED.read_text(encoding='utf-8'))
    found = [x for x in rec['items'] if x['status'] == 'recovered']
    if not found:
        die('recovered_39.json 没有 recovered 项')
    url, label = db_url()
    rows = load_db(url)
    if len(rows) != 931:
        die(f'linked mock questions {len(rows)} ≠ 931')
    by_qid = {f'mock_{r["sid"]}_q{r["question_no"]:02d}': r for r in rows}
    plan = {'updates': [], 'inserts': [], 'questions': [], 'unchanged': [], 'errors': []}
    for x in found:
        r = by_qid.get(x['qid'])
        if not r:
            plan['errors'].append(f'{x["qid"]}: 找不到 PG question/chunk')
            continue
        text = x['text']
        if not text or len(text) < 10:
            plan['errors'].append(f'{x["qid"]}: recovered 文本为空/过短')
            continue
        if r['text'] == text and r['hash'] == h(text):
            plan['unchanged'].append(x['qid'])
            continue
        if x['reason'] == 'set_has_no_segment':
            # 整套缺段：新建 chunk（原 chunk 若存在且多题则保留；这里通常原 chunk 文本无题号）
            repair_key = f'{r["sid"]}:{r["chunk_key"]}:ocr39'
            new_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'chilon-mock-ocr:' + repair_key))
            loc = dict(r['locator']) if isinstance(r['locator'], dict) else {}
            loc.update({'repair': OCR_TAG, 'repair_key': repair_key,
                        'origin_chunk_id': r['chunk_id']})
            plan['inserts'].append({'qid': x['qid'], 'new_id': new_id, 'repair_key': repair_key,
                                    'dv': r['dv'], 'chunk_key': f'{r["chunk_key"]}_ocr39',
                                    'ordinal': r['ordinal'], 'text': text, 'hash': h(text),
                                    'locator': loc, 'kind': r['kind'], 'parser': r['parser'],
                                    'schema': r['schema'], 'source_chunk_id': r['chunk_id']})
            plan['questions'].append({'qid': x['qid'], 'question_id': r['question_id'],
                                      'old': r['stem_locator'], 'new': loc})
        else:
            plan['updates'].append({'qid': x['qid'], 'chunk_id': r['chunk_id'],
                                    'chunk_key': r['chunk_key'], 'old_text': r['text'],
                                    'old_hash': r['hash'], 'text': text, 'hash': h(text)})
    changes = len(plan['updates']) + len(plan['inserts']) + len(plan['questions'])
    # 备份（pre-apply 全量 mock chunk/question 行；已有则保留并更新 rollback，仅当本次有变更）
    if not BACKUP.exists() or (args.force_backup and changes):
        import psycopg
        conn = psycopg.connect(url)
        cur = conn.cursor()
        cur.execute("""SELECT c.id::text, c.document_version_id::text, c.chunk_key, c.ordinal,
            c.text_content, c.text_hash, c.locator, c.content_kind, c.parser_version,
            c.parse_schema_version, c.created_at::text, s.id::text, s.title
            FROM knowledge_chunks c JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
            JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
        chunks = [dict(zip(['id', 'dv', 'chunk_key', 'ordinal', 'text', 'hash', 'locator',
                            'kind', 'parser', 'schema', 'created', 'sid', 'title'], row))
                  for row in cur.fetchall()]
        cur.execute("""SELECT q.id::text, q.document_version_id::text, q.question_no,
            q.stem_locator, q.ordinal, q.updated_at::text, s.id::text
            FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
            JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
        questions = [dict(zip(['id', 'dv', 'question_no', 'stem_locator', 'ordinal',
                               'updated_at', 'sid'], row)) for row in cur.fetchall()]
        conn.close()
        backup = {'schema': 'chilon-ocr39-backup/v1', 'repair_tag': OCR_TAG,
                  'chunks': chunks, 'questions': questions, 'plan': plan,
                  'rollback': {
                      'delete_chunk_ids': [x['new_id'] for x in plan['inserts']],
                      'restore_chunk_texts': [{'id': x['chunk_id'], 'text': x['old_text'],
                                               'hash': x['old_hash']} for x in plan['updates']],
                      'restore_question_locators': [{'id': x['question_id'], 'old': x['old'],
                                                     'new': x['new']} for x in plan['questions']],
                  }}
        OUT.mkdir(parents=True, exist_ok=True)
        BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[备份] {BACKUP}（chunks {len(chunks)} / questions {len(questions)}）')
    else:
        print(f'[备份] 保留已有 {BACKUP}')
    print(f'[计划] update {len(plan["updates"])}｜insert {len(plan["inserts"])}｜'
          f'question locator {len(plan["questions"])}｜unchanged {len(plan["unchanged"])}｜'
          f'errors {len(plan["errors"])}')
    if plan['errors']:
        for e in plan['errors']:
            print('  -', e)
        return 2
    if args.dry_run:
        print('[dry-run] 未写 PG')
        return 0
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            for x in plan['updates']:
                cur.execute('UPDATE knowledge_chunks SET text_content=%s, text_hash=%s '
                            'WHERE id=%s AND (text_content IS DISTINCT FROM %s OR text_hash IS DISTINCT FROM %s)',
                            (x['text'], x['hash'], x['chunk_id'], x['text'], x['hash']))
            for x in plan['inserts']:
                cur.execute("""INSERT INTO knowledge_chunks
                    (id, document_version_id, chunk_key, ordinal, text_content, text_hash,
                     locator, content_kind, parser_version, parse_schema_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET text_content=EXCLUDED.text_content,
                    text_hash=EXCLUDED.text_hash, locator=EXCLUDED.locator""",
                    (x['new_id'], x['dv'], x['chunk_key'], x['ordinal'], x['text'], x['hash'],
                     json.dumps(x['locator'], ensure_ascii=False), x['kind'], x['parser'], x['schema']))
            for x in plan['questions']:
                cur.execute('UPDATE knowledge_questions SET stem_locator=%s::jsonb, updated_at=now() '
                            'WHERE id=%s AND stem_locator IS DISTINCT FROM %s::jsonb',
                            (json.dumps(x['new'], ensure_ascii=False), x['question_id'],
                             json.dumps(x['new'], ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    # 校验
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("""SELECT count(*) FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    total = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM knowledge_questions q
        JOIN knowledge_chunks c ON c.document_version_id=q.document_version_id AND c.locator=q.stem_locator
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    linked = cur.fetchone()[0]
    cur.execute('SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NULL')
    ann = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FILTER (WHERE cardinality(coalesce(q.current_knowledge_points,'{}'))>0)
        FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    pts = cur.fetchone()[0]
    cur.execute("""SELECT (SELECT count(*) FROM knowledge_sources WHERE source_type='gaokao_paper'),
        (SELECT count(*) FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
         JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='gaokao_paper')""")
    gk = cur.fetchone()
    conn.close()
    print(f'[apply] chunks {total}｜linked {linked}｜annotations {ann}｜mock_points {pts}｜gk {gk}')
    # 幂等复跑
    rows2 = load_db(url)
    print(f'[apply] linked question rows {len(rows2)}（应 931）')
    return 0


def stage_rollback(args):
    import psycopg
    if not BACKUP.exists():
        die(f'找不到备份 {BACKUP}')
    b = json.loads(BACKUP.read_text(encoding='utf-8'))
    url, _label = db_url()
    print(f'[rollback] 删除新 chunk {len(b["rollback"]["delete_chunk_ids"])}｜'
          f'恢复 chunk 文本 {len(b["rollback"]["restore_chunk_texts"])}｜'
          f'恢复 question locator {len(b["rollback"]["restore_question_locators"])}')
    if args.dry_run:
        print('[rollback] dry-run，未写 PG')
        return 0
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            ids = b['rollback']['delete_chunk_ids']
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


def main(argv=None):
    ap = argparse.ArgumentParser(description='阿里云试卷切题批量 OCR / 回填 39 题')
    ap.add_argument('--stage', choices=['ocr', 'apply', 'rollback'], default='ocr')
    ap.add_argument('--only-pdf', default=None, help='只处理标题/路径包含该字符串的 PDF（测试用）')
    ap.add_argument('--no-photo', action='store_true', help='不尝试 photo 兜底')
    ap.add_argument('--dry-run', action='store_true', help='apply/rollback 只打印计划')
    ap.add_argument('--force-backup', action='store_true', help='apply 时重写备份')
    args = ap.parse_args(argv)
    if args.stage == 'ocr':
        return stage_ocr(args)
    if args.stage == 'apply':
        return stage_apply(args)
    return stage_rollback(args)


if __name__ == '__main__':
    sys.exit(main())
