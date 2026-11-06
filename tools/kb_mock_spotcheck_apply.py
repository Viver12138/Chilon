#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""93 题教师抽检修正：解析回填表 → 计算一致率 → 写 PG/卡片修正（不调 OCR）。

阶段：
  --stage parse    解析教师回填 txt，输出 spotcheck_parsed.json + spotcheck_result.md
  --stage apply    备份后把 93 题改为教师判定（primary=教师考点，secondary 清空，
                   classification_source='teacher'，confidence=1.0，
                   model_version='spotcheck-2026-11-06'），幂等；输出 spotcheck_apply_report.md
  --stage rollback 从 backup_spotcheck_2026-11-06.json 回滚

卡片重投影使用现有 tools/project_restricted_corpus.py --only mock --force-generated，
本工具不直接写卡片。

词表默认 `corpus/eval/kp_vocab.md`（仓库内副本），可用 CHILON_KP_VOCAB 覆盖；
parse 需要 `--source` 或 CHILON_SPOTCHECK_SOURCE（不内置个人路径）。
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = ROOT / 'var' / 'mock_annotations' / 'full'
PARSED = FULL / 'spotcheck_parsed.json'
RESULT = FULL / 'spotcheck_result.md'
APPLY_REPORT = FULL / 'spotcheck_apply_report.md'
BACKUP = FULL / 'backup_spotcheck_2026-11-06.json'
ANNOTATIONS = FULL / 'annotations_931.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
MODEL_VERSION = 'spotcheck-2026-11-06'
TEACHER_SOURCE = 'teacher'


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


def load_vocab():
    t = VOCAB_MD.read_text(encoding='utf-8')
    vocab = set()
    for line in t.splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
            vocab.add(parts[0].strip('`'))
    if len(vocab) != 120:
        raise SystemExit(f'词表 {len(vocab)} 项 ≠ 120')
    return vocab


def parse_spot(source: pathlib.Path):
    if not source.exists():
        die(f'找不到 {source}')
    rows = []
    for line in source.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) != 8 or not re.fullmatch(r'\d+', parts[0]):
            continue
        rows.append({'index': int(parts[0]), 'qid': parts[1], 'teacher_module_id': parts[2],
                     'teacher_module_name': parts[3], 'teacher_kp': parts[4],
                     'teacher_kp_name': parts[5], 'user_category': parts[6], 'note': parts[7]})
    if len(rows) != 93:
        die(f'解析到 {len(rows)} 行，应为 93')
    ann = {x['qid']: x for x in json.loads(ANNOTATIONS.read_text(encoding='utf-8'))['items']}
    vocab = load_vocab()
    errors = []
    qids = [r['qid'] for r in rows]
    if len(set(qids)) != 93:
        errors.append('qid 不唯一')
    for r in rows:
        if r['qid'] not in ann:
            errors.append(f'{r["qid"]}: 不在 annotations_931')
        if r['teacher_kp'] not in vocab:
            errors.append(f'{r["qid"]}: 教师 kp 非法 {r["teacher_kp"]}')
        if not re.fullmatch(r'kp_\d{2}_[a-z_]+', r['teacher_module_id']):
            errors.append(f'{r["qid"]}: 教师模块 ID 格式异常 {r["teacher_module_id"]}')
    # 计算
    same_mod = same_exact = same_any = 0
    mismatch = []
    cat_diff = []
    comp_cats = collections.Counter()
    for r in rows:
        a = ann[r['qid']]
        p = a['kp_primary']
        module_same = bool(p) and p.split('_')[1] == r['teacher_module_id'].split('_')[1]
        exact = p == r['teacher_kp']
        anymatch = r['teacher_kp'] in (([p] if p else []) + list(a['kp_secondary']))
        same_mod += module_same
        same_exact += exact
        same_any += anymatch
        if not p:
            comp = '模型为空'
        elif not module_same:
            comp = '模块不一致'
        elif exact:
            comp = '模块一致、考点一致'
        else:
            comp = '模块一致、考点不一致'
        comp_cats[comp] += 1
        if comp != r['user_category']:
            if r['user_category'] == '模块一致、考点偏' and comp == '模块一致、考点不一致':
                reason = '用户把同模块的“考点偏”单列；计算口径按 exact 归类为“模块一致、考点不一致”'
            elif r['user_category'] == '模块不一致' and comp == '模块一致、考点不一致':
                reason = '用户按更细的二级模块（如解三角形/圆锥曲线/计数子类）判定；120 词表按 kp_XX 模块前缀计算为同模块'
            else:
                reason = '用户自评与计算口径不同'
            cat_diff.append({'qid': r['qid'], 'user_category': r['user_category'],
                             'computed_category': comp, 'reason': reason})
        if not exact:
            mismatch.append({'qid': r['qid'], 'teacher_module': r['teacher_module_name'],
                             'teacher_kp': r['teacher_kp'], 'teacher_kp_name': r['teacher_kp_name'],
                             'model_primary': p, 'model_secondary': a['kp_secondary'],
                             'model_confidence': a['confidence'],
                             'user_category': r['user_category'], 'note': r['note']})
    empty_in_sample = [r['qid'] for r in rows if not ann[r['qid']]['kp_primary']]
    all_empty = [q for q, a in ann.items() if not a['kp_primary']]
    remain_empty = [q for q in all_empty if q not in set(qids)]
    payload = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'total': len(rows), 'errors': errors,
               'metrics': {'module_consistent': same_mod, 'module_pct': round(same_mod / 93 * 100, 1),
                           'exact': same_exact, 'exact_pct': round(same_exact / 93 * 100, 1),
                           'primary_plus_secondary': same_any,
                           'primary_plus_secondary_pct': round(same_any / 93 * 100, 1),
                           'mismatch': 93 - same_exact},
               'computed_categories': dict(comp_cats),
               'user_categories': dict(collections.Counter(r['user_category'] for r in rows)),
               'category_differences': cat_diff,
               'mismatches': mismatch,
               'empty_in_sample': empty_in_sample,
               'remaining_empty_after_correction': len(remain_empty),
               'remaining_empty_qids': remain_empty,
               'rows': rows}
    FULL.mkdir(parents=True, exist_ok=True)
    PARSED.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    # 结果报告
    L = ['---', 'type: report', 'title: 93 题教师抽检结果（修正前）', 'updated: 2026-11-06',
         'status: parsed', '---', '',
         '# 93 题教师抽检结果（修正前基线）', '',
         f'> 来源：`{source}`；sha256 `{payload["source_sha256"][:16]}…`；教师判定不改算法。', '',
         '## 1. 一致率', '',
         '| 指标 | 结果 |', '| --- | --- |',
         f'| 模块一致 | **{same_mod}/93 = {same_mod/93*100:.1f}%** |',
         f'| 考点 exact | **{same_exact}/93 = {same_exact/93*100:.1f}%** |',
         f'| primary+secondary 命中 | **{same_any}/93 = {same_any/93*100:.1f}%** |',
         f'| 考点不一致 | **{93-same_exact}/93** |', '',
         '## 2. 用户自评 vs 计算口径差异', '',
         f'- 用户自评分布：{dict(collections.Counter(r["user_category"] for r in rows))}',
         f'- 计算分布：{dict(comp_cats)}',
         f'- 差异条目：**{len(cat_diff)}**（不修改教师判定；仅说明口径）', '',
         '| qid | 用户自评 | 计算 | 原因 |', '| --- | --- | --- | --- |']
    for d in cat_diff:
        L.append(f'| `{d["qid"]}` | {d["user_category"]} | {d["computed_category"]} | {d["reason"]} |')
    L += ['', '## 3. 42 题逐条差异（教师考点 ≠ 模型 primary）', '',
          '| # | qid | 教师考点 | 模型 primary | 用户自评 | 备注 |', '| --- | --- | --- | --- | --- | --- |']
    for i, m in enumerate(mismatch, 1):
        L.append(f'| {i} | `{m["qid"]}` | `{m["teacher_kp"]}` {m["teacher_kp_name"]} | '
                 f'`{m["model_primary"]}` | {m["user_category"]} | {m["note"]} |')
    L += ['', '## 4. 空 primary', '',
          f'- 全量空 primary：**{len(all_empty)}**；样本内空：**{len(empty_in_sample)}**（{empty_in_sample}）',
          f'- 修正后仍空：**{len(remain_empty)}**（不在样本内的 {len(remain_empty)} 条）', '',
          '| qid | 套 | 备注 |', '| --- | --- | --- |']
    for q in remain_empty:
        L.append(f'| `{q}` | {ann[q]["set_title"]} | 模型证据不足，未硬塞；建议后续人工补 |')
    L += ['', '## 5. 结论', '',
          '- 93 题按教师判定修正（primary=教师考点、secondary 清空、classification_source=teacher）；'
          '其余 **838 题**保留模型标注。', '',
          '---', '', '> 解析 JSON：`spotcheck_parsed.json`。', '']
    RESULT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[parse] {len(rows)}/93；模块 {same_mod}（{same_mod/93*100:.1f}%）；'
          f'exact {same_exact}（{same_exact/93*100:.1f}%）；any {same_any}；差异 {len(mismatch)}；'
          f'自评差异 {len(cat_diff)}；空样本 {len(empty_in_sample)}；修正后仍空 {len(remain_empty)}')
    if errors:
        for e in errors:
            print('  -', e)
        return 2
    print(f'输出：{PARSED}\n报告：{RESULT}')
    return 0


def _qmap(cur):
    cur.execute("""
        SELECT s.id::text, q.question_no, q.id::text
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam'
    """)
    return {f'mock_{sid}_q{int(no):02d}': qid for sid, no, qid in cur.fetchall()}


def stage_apply(args):
    import psycopg
    p = json.loads(PARSED.read_text(encoding='utf-8'))
    rows = p['rows']
    url = db_url()
    conn = psycopg.connect(url); cur = conn.cursor()
    qmap = _qmap(cur)
    if len(qmap) != 931:
        die(f'PG mock questions {len(qmap)} ≠ 931')
    qids = [r['qid'] for r in rows]
    # 备份这些 93 题的 active annotations
    cur.execute("""
        SELECT a.id::text, a.question_id::text, a.annotation_type, a.value,
               a.classification_source, a.confidence::float8, a.model_version, a.created_at::text
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        WHERE a.superseded_by IS NULL AND q.id = ANY(%s::uuid[])
        ORDER BY a.question_id, a.annotation_type
    """, ([qmap[q] for q in qids],))
    existing = [dict(zip(['id','question_id','type','value','source','confidence','model_version','created_at'], r))
                for r in cur.fetchall()]
    conn.close()
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps({'schema': 'chilon-spotcheck-backup/v1',
                                      'model_version': MODEL_VERSION,
                                      'items': rows,
                                      'annotations': existing}, ensure_ascii=False, indent=1),
                          encoding='utf-8')
        print(f'[备份] {BACKUP}（93 题现有 active annotations {len(existing)}）')
    else:
        print(f'[备份] 保留已有 {BACKUP}')
    plan = {'primary_update': 0, 'primary_insert': 0, 'secondary_delete': 0, 'unchanged': 0}
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            for r in rows:
                qid = qmap[r['qid']]
                # primary upsert
                cur.execute("""SELECT id::text, value, classification_source, confidence::float8, model_version
                    FROM knowledge_annotations WHERE question_id=%s::uuid AND annotation_type='kp_primary'
                      AND superseded_by IS NULL""", (qid,))
                row = cur.fetchone()
                if row and row[1] == r['teacher_kp'] and row[2] == TEACHER_SOURCE \
                        and abs(float(row[3]) - 1.0) < 1e-9 and row[4] == MODEL_VERSION:
                    plan['unchanged'] += 1
                elif row:
                    cur.execute("""UPDATE knowledge_annotations
                        SET value=%s, classification_source=%s, confidence=1.0, model_version=%s
                        WHERE id=%s::uuid""", (r['teacher_kp'], TEACHER_SOURCE, MODEL_VERSION, row[0]))
                    plan['primary_update'] += 1
                else:
                    cur.execute("""INSERT INTO knowledge_annotations
                        (id, question_id, annotation_type, value, classification_source,
                         confidence, model_version)
                        VALUES (%s::uuid,%s::uuid,'kp_primary',%s,%s,1.0,%s)""",
                                (str(uuid.uuid4()), qid, r['teacher_kp'], TEACHER_SOURCE, MODEL_VERSION))
                    plan['primary_insert'] += 1
                # secondary 清空
                cur.execute("""DELETE FROM knowledge_annotations
                    WHERE question_id=%s::uuid AND annotation_type='kp_secondary' AND superseded_by IS NULL""",
                            (qid,))
                plan['secondary_delete'] += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    # 校验
    conn = psycopg.connect(url); cur = conn.cursor()
    cur.execute("""SELECT a.annotation_type, count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL GROUP BY 1""")
    mock_counts = dict(cur.fetchall())
    cur.execute("""SELECT count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL
          AND a.annotation_type='kp_primary' AND a.value<>''""")
    primary_nonempty = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL
          AND a.annotation_type='kp_primary' AND a.classification_source='teacher'""")
    teacher_count = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='gaokao_paper' AND a.superseded_by IS NULL""")
    gk_ann = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FILTER (WHERE cardinality(coalesce(q.current_knowledge_points,'{}'))>0)
        FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    mock_points = cur.fetchone()[0]
    conn.close()
    # 幂等检查
    changed = 0
    conn = psycopg.connect(url); cur = conn.cursor()
    for r in rows:
        qid = qmap[r['qid']]
        cur.execute("""SELECT value, classification_source, confidence::float8, model_version
            FROM knowledge_annotations WHERE question_id=%s::uuid AND annotation_type='kp_primary'
              AND superseded_by IS NULL""", (qid,))
        row = cur.fetchone()
        if (not row or row[0] != r['teacher_kp'] or row[1] != TEACHER_SOURCE
                or abs(float(row[2]) - 1.0) > 1e-9 or row[3] != MODEL_VERSION):
            changed += 1
        cur.execute("""SELECT count(*) FROM knowledge_annotations
            WHERE question_id=%s::uuid AND annotation_type='kp_secondary' AND superseded_by IS NULL""",
                    (qid,))
        if cur.fetchone()[0]:
            changed += 1
    conn.close()
    L = ['---', 'type: report', 'title: 93 题教师抽检修正 apply 报告', 'updated: 2026-11-06',
         'status: done', '---', '',
         '# 93 题教师抽检修正 · PG apply 报告', '',
         '> 只改这 93 题；其余 838 题保持模型标注；不写 legacy、不动高考、不调 OCR。', '',
         '## 变更计数', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| primary 更新 | {plan["primary_update"]} |',
         f'| primary 新增（原空） | {plan["primary_insert"]} |',
         f'| secondary 删除 | {plan["secondary_delete"]} |',
         f'| 幂等跳过 | {plan["unchanged"]} |',
         f'| mock active primary 行 | {mock_counts.get("kp_primary", 0)} |',
         f'| mock active secondary 行 | {mock_counts.get("kp_secondary", 0)} |',
         f'| primary 非空 | {primary_nonempty}（修正前 910） |',
         f'| teacher 来源 primary | {teacher_count}（应 93） |',
         f'| 高考 annotations active | {gk_ann}（应 8007） |',
         f'| mock legacy points 非空 | {mock_points}（应 793） |',
         f'| 幂等复跑变化 | {changed}（应 0） |', '',
         f'- 备份：`{BACKUP}`', '',
         '## 校验', '',
         f'- 931 primary 行不变；secondary 由 230 减为 {mock_counts.get("kp_secondary", 0)}（93 题清空）',
         f'- 修正后 primary 非空 **{primary_nonempty}**；空 primary **{931-primary_nonempty}**（21-2=19）',
         f'- 93 题 classification_source=teacher、confidence=1.0、model_version=`{MODEL_VERSION}`',
         '', '---', '', '> 回滚：`tools/kb_mock_spotcheck_apply.py --stage rollback`；'
         '卡片重投影：`tools/project_restricted_corpus.py --only mock --apply --force-generated`。', '']
    APPLY_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[apply] primary {mock_counts.get("kp_primary",0)}｜secondary {mock_counts.get("kp_secondary",0)}｜'
          f'nonempty {primary_nonempty}｜teacher {teacher_count}｜gk {gk_ann}｜幂等变化 {changed}')
    return 0 if (teacher_count == 93 and primary_nonempty == 912 and gk_ann == 8007 and changed == 0) else 4


def stage_rollback(args):
    import psycopg
    if not BACKUP.exists():
        die(f'找不到 {BACKUP}')
    b = json.loads(BACKUP.read_text(encoding='utf-8'))
    url = db_url()
    conn = psycopg.connect(url); cur = conn.cursor()
    qmap = _qmap(cur)
    qids = [qmap[r['qid']] for r in b['items']]
    old_ids = {a['id'] for a in b['annotations']}
    print(f'[rollback] 删除本工具新增的 93 题 teacher rows，恢复备份 {len(old_ids)} 行')
    if args.dry_run:
        print('[rollback] dry-run，未写 PG')
        conn.close()
        return 0
    try:
        with conn.transaction():
            cur = conn.cursor()
            # 删除 93 题当前 active rows（teacher/model），随后按备份恢复
            cur.execute("""SELECT id::text FROM knowledge_annotations
                WHERE question_id = ANY(%s::uuid[]) AND superseded_by IS NULL""", (qids,))
            current_ids = [r[0] for r in cur.fetchall()]
            if current_ids:
                cur.execute('DELETE FROM knowledge_annotations WHERE id = ANY(%s::uuid[])', (current_ids,))
            for a in b['annotations']:
                cur.execute("""INSERT INTO knowledge_annotations
                    (id, question_id, annotation_type, value, classification_source,
                     confidence, model_version, created_at)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s::numeric,%s,coalesce(%s::timestamptz,now()))""",
                            (a['id'], a['question_id'], a['type'], a['value'], a['source'],
                             a['confidence'], a['model_version'], a['created_at']))
        conn.commit()
    finally:
        conn.close()
    print('[rollback] 完成')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='93 题教师抽检修正')
    ap.add_argument('--stage', choices=['parse', 'apply', 'rollback'], default='parse')
    ap.add_argument('--source', default=os.environ.get('CHILON_SPOTCHECK_SOURCE'),
                    help='教师回填 txt 路径（parse 必需；默认读 CHILON_SPOTCHECK_SOURCE）')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    if args.stage == 'parse':
        if not args.source:
            ap.error('必须提供 --source 或 CHILON_SPOTCHECK_SOURCE')
        return parse_spot(pathlib.Path(args.source))
    if args.stage == 'apply':
        return stage_apply(args)
    return stage_rollback(args)


if __name__ == '__main__':
    sys.exit(main())
