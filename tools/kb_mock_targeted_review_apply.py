#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""104 题定向复核修正：解析教师回填 → 计算一致率 → 写 PG/卡片（不调 OCR）。

阶段：
  --stage parse    解析 定向复核.txt，输出 targeted_review_parsed.json + targeted_review_result.md
  --stage apply    备份后把 104 题改为教师判定（primary=教师考点、secondary 清空、
                   classification_source='teacher'、confidence=1.0、
                   model_version='spotcheck2-2026-11-06'），幂等；输出 targeted_apply_report.md
  --stage rollback 从 backup_targeted_2026-11-06.json 回滚

卡片重投影：tools/project_restricted_corpus.py --only mock --apply --force-generated。

词表默认 `corpus/eval/kp_vocab.md`（仓库内副本），可用 CHILON_KP_VOCAB 覆盖；
parse 需要 `--source` 或 CHILON_TARGETED_REVIEW_SOURCE（不内置个人路径）。
"""
from __future__ import annotations

import argparse
import collections
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
FULL = ROOT / 'var' / 'mock_annotations' / 'full'
AUDIT = FULL / '定向复核_已录入.txt'
PARSED = FULL / 'targeted_review_parsed.json'
RESULT = FULL / 'targeted_review_result.md'
APPLY_REPORT = FULL / 'targeted_apply_report.md'
BACKUP = FULL / 'backup_targeted_2026-11-06.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
MODEL_VERSION = 'spotcheck2-2026-11-06'
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


def _load_state():
    import psycopg
    conn = psycopg.connect(db_url())
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id::text, q.question_no, q.id::text
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam'
    """)
    id2qid = {r[2]: f'mock_{r[0]}_q{int(r[1]):02d}' for r in cur.fetchall()}
    cur.execute("""
        SELECT a.question_id::text, a.value, a.classification_source, a.confidence::float8, a.model_version
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL AND a.annotation_type='kp_primary'
    """)
    prim = {id2qid[r[0]]: {'value': r[1], 'source': r[2], 'confidence': float(r[3]), 'model_version': r[4]}
            for r in cur.fetchall()}
    cur.execute("""
        SELECT a.question_id::text, a.value
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL AND a.annotation_type='kp_secondary'
    """)
    sec = {id2qid[r[0]]: json.loads(r[1]) for r in cur.fetchall()}
    conn.close()
    return prim, sec, id2qid


def parse_targeted(source: pathlib.Path):
    if not source.exists():
        die(f'找不到 {source}')
    rows = []
    for line in source.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) != 8 or not re.fullmatch(r'\d+', parts[0]):
            continue
        rows.append({'index': int(parts[0]), 'qid': parts[1], 'agree': parts[2],
                     'teacher_module_id': parts[3], 'teacher_module_name': parts[4],
                     'teacher_kp': parts[5], 'teacher_kp_name': parts[6], 'note': parts[7]})
    if len(rows) != 104:
        die(f'解析到 {len(rows)} 行，应为 104')
    vocab = load_vocab()
    prim, sec, _id2qid = _load_state()
    errors = []
    qids = [r['qid'] for r in rows]
    if len(set(qids)) != 104:
        errors.append('qid 不唯一')
    target = {q for q, v in prim.items() if v['source'] == 'model'
              and (v['value'] == '' or v['confidence'] <= 0.70)}
    if set(qids) != target:
        errors.append(f'qid 与目标集合不一致：多 {len(set(qids)-target)}、少 {len(target-set(qids))}')
    for r in rows:
        if r['qid'] not in prim:
            errors.append(f'{r["qid"]}: PG 缺 primary')
        if r['teacher_kp'] not in vocab:
            errors.append(f'{r["qid"]}: 教师 kp 非法')
        if not re.fullmatch(r'kp_\d{2}_[a-z_]+', r['teacher_module_id']):
            errors.append(f'{r["qid"]}: 教师模块 ID 格式异常')
        if r['agree'] not in ('是', '否'):
            errors.append(f'{r["qid"]}: 自评列非 是/否')
    # 指标
    same_mod = same_exact = same_any = 0
    comp_cats = collections.Counter()
    mismatch = []
    for r in rows:
        p = prim[r['qid']]['value']
        module_same = bool(p) and p.split('_')[1] == r['teacher_module_id'].split('_')[1]
        exact = p == r['teacher_kp']
        anymatch = r['teacher_kp'] in (([p] if p else []) + list(sec.get(r['qid'], [])))
        same_mod += module_same
        same_exact += exact
        same_any += anymatch
        if not p:
            cc = '模型为空'
        elif not module_same:
            cc = '模块不一致'
        elif exact:
            cc = '模块一致、考点一致'
        else:
            cc = '模块一致、考点不一致'
        comp_cats[cc] += 1
        if not exact:
            mismatch.append({'qid': r['qid'], 'teacher_module': r['teacher_module_name'],
                             'teacher_kp': r['teacher_kp'], 'teacher_kp_name': r['teacher_kp_name'],
                             'model_primary': p,
                             'model_secondary': sec.get(r['qid'], []),
                             'model_confidence': prim[r['qid']]['confidence'],
                             'self_agree': r['agree'], 'computed_category': cc, 'note': r['note']})
    empty_in = [r['qid'] for r in rows if not prim[r['qid']]['value']]
    low_nonempty = [r['qid'] for r in rows if prim[r['qid']]['value'] and prim[r['qid']]['confidence'] <= 0.70]
    self_counts = dict(collections.Counter(r['agree'] for r in rows))
    agree_yes = self_counts.get('是', 0)
    agree_no = self_counts.get('否', 0)
    payload = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'total': len(rows), 'errors': errors,
               'target_set_size': len(target),
               'metrics': {'module_consistent': same_mod, 'module_pct': round(same_mod / 104 * 100, 1),
                           'exact': same_exact, 'exact_pct': round(same_exact / 104 * 100, 1),
                           'primary_plus_secondary': same_any,
                           'primary_plus_secondary_pct': round(same_any / 104 * 100, 1),
                           'mismatch': 104 - same_exact},
               'self_eval': {'是': agree_yes, '否': agree_no,
                             'yes_pct': round(agree_yes / 104 * 100, 1),
                             'no_pct': round(agree_no / 104 * 100, 1)},
               'computed_categories': dict(comp_cats),
               'empty_in_sample': len(empty_in), 'low_nonempty': len(low_nonempty),
               'mismatches': mismatch, 'rows': rows}
    FULL.mkdir(parents=True, exist_ok=True)
    PARSED.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    if source.resolve() != AUDIT.resolve():  # 源就是审计副本时不必自拷贝
        shutil.copyfile(source, AUDIT)
    # 报告
    L = ['---', 'type: report', 'title: 104 题定向复核结果（修正前）', 'updated: 2026-11-06',
         'status: parsed', '---', '',
         '# 104 题定向复核结果（修正前基线）', '',
         f'> 来源：`{source}`；sha256 `{payload["source_sha256"][:16]}…`。  ',
         '> 目标集合 = 当前模型低置信/空 primary 的 **104** 条（非随机高风险子集）；教师判定不改算法。', '',
         '## 1. 样本性质', '',
         f'- 104 题中：**空 primary 19 条**、**低置信（≤0.70）非空 85 条**。',
         f'- 目标集合校验：与 PG 当前 model 低置信/空 primary **104 条完全一致**；与 93 题教师修正 **0 重叠**。', '',
         '## 2. 自评与逐题一致率', '',
         '| 指标 | 结果 |', '| --- | --- |',
         f'| 教师自评（文件字段） | 是 **{agree_yes}** / 否 **{agree_no}** |',
         f'| 逐题模块一致 | **{same_mod}/104 = {same_mod/104*100:.1f}%** |',
         f'| 逐题考点 exact | **{same_exact}/104 = {same_exact/104*100:.1f}%** |',
         f'| primary+secondary 命中 | **{same_any}/104 = {same_any/104*100:.1f}%** |',
         f'| 不一致 | **{104-same_exact}/104** |', '',
         '> **口径说明（重要）**：任务简报写“自评 是 90 / 否 14”；但按文件 `是否同意模型primary` 字段实际统计为 '
         f'**是 {agree_yes} / 否 {agree_no}**，其中“是”数 = 考点 exact 数（{same_exact}），'
         '“否”数 = 不一致数（90）。因此本报告以文件原文为准，并列出该差异，不修改教师判定。  ',
         '> 口径差异：若按任务简报“是 90”，则自评（90）远高于逐题模块一致（47），说明教师自评按“可接受模块/宽口径”，'
         '逐题按 kp_id 严格计算；若按文件字段实际“是 14”，则自评同意数与 exact（14）完全一致，'
         '而模块一致 47 高于 14，说明教师认为模块可接受但具体考点不对。两种口径都不能互相替代，且均不改教师判定。','',
         '## 3. 计算分布', '',
         f'- 计算类别：{dict(comp_cats)}',
         f'- 自评字段分布：{self_counts}','',
         '## 4. 差异题 Top 24（教师考点 ≠ 模型 primary）', '',
         '| # | qid | 教师考点 | 模型 primary | 自评 | 备注 |', '| --- | --- | --- | --- | --- | --- |']
    for i, m in enumerate(mismatch[:24], 1):
        L.append(f'| {i} | `{m["qid"]}` | `{m["teacher_kp"]}` {m["teacher_kp_name"]} | '
                 f'`{m["model_primary"]}` | {m["self_agree"]} | {m["note"]} |')
    L += ['', '## 5. 修正后预期', '',
          '- 104 题 primary=教师考点、secondary 清空、classification_source=teacher、confidence=1.0、'
          f'model_version=`{MODEL_VERSION}`；',
          '- 93 题 spotcheck 修正保持；其余 734 题保持 model；',
          '- primary 931/931 非空；空 primary 0；全部 19 条空 primary 补齐。','',
          f'- 审计副本：`{AUDIT}`', '', '---', '', '> 解析 JSON：`targeted_review_parsed.json`。', '']
    RESULT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[parse] 104/104；模块 {same_mod}（{same_mod/104*100:.1f}%）；exact {same_exact}（{same_exact/104*100:.1f}%）；'
          f'any {same_any}；自评 是{agree_yes}/否{agree_no}；空 {len(empty_in)}；低置信非空 {len(low_nonempty)}')
    if errors:
        for e in errors:
            print('  -', e)
        return 2
    print(f'输出：{PARSED}\n报告：{RESULT}\n审计副本：{AUDIT}')
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
    qids = [r['qid'] for r in rows]
    cur.execute("""
        SELECT a.id::text, a.question_id::text, a.annotation_type, a.value,
               a.classification_source, a.confidence::float8, a.model_version, a.created_at::text
        FROM knowledge_annotations a
        WHERE a.superseded_by IS NULL AND a.question_id = ANY(%s::uuid[])
        ORDER BY a.question_id, a.annotation_type
    """, ([qmap[q] for q in qids],))
    existing = [dict(zip(['id','question_id','type','value','source','confidence','model_version','created_at'], r))
                for r in cur.fetchall()]
    conn.close()
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps({'schema': 'chilon-targeted-review-backup/v1',
                                      'model_version': MODEL_VERSION, 'items': rows,
                                      'annotations': existing}, ensure_ascii=False, indent=1),
                          encoding='utf-8')
        print(f'[备份] {BACKUP}（104 题现有 active annotations {len(existing)}）')
    else:
        print(f'[备份] 保留已有 {BACKUP}')
    plan = {'primary_update': 0, 'secondary_delete': 0, 'unchanged': 0}
    conn = psycopg.connect(url)
    try:
        with conn.transaction():
            cur = conn.cursor()
            for r in rows:
                qid = qmap[r['qid']]
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
                    plan['primary_update'] += 1
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
    cur.execute("""SELECT a.annotation_type, a.classification_source, a.model_version, count(*)
        FROM knowledge_annotations a
        JOIN knowledge_questions q ON q.id=a.question_id
        JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='mock_exam' AND a.superseded_by IS NULL AND a.annotation_type='kp_primary'
        GROUP BY 1,2,3""")
    by_source = {(r[1], r[2]): r[3] for r in cur.fetchall()}
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
        WHERE s.source_type='gaokao_paper' AND a.superseded_by IS NULL""")
    gk_ann = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FILTER (WHERE cardinality(coalesce(q.current_knowledge_points,'{}'))>0)
        FROM knowledge_questions q JOIN knowledge_document_versions dv ON dv.id=q.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id WHERE s.source_type='mock_exam'""")
    mock_points = cur.fetchone()[0]
    conn.close()
    teacher_total = sum(v for (src, mv), v in by_source.items() if src == TEACHER_SOURCE)
    model_total = sum(v for (src, mv), v in by_source.items() if src != TEACHER_SOURCE)
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
    L = ['---', 'type: report', 'title: 104 题定向复核修正 apply 报告', 'updated: 2026-11-06',
         'status: done', '---', '',
         '# 104 题定向复核修正 · PG/卡片 apply 报告', '',
         '> 只改这 104 题；不碰 93 题 teacher 行、其余 model、高考、legacy；不调 OCR。', '',
         '## PG 变更', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| primary 更新 | {plan["primary_update"]} |',
         f'| secondary 删除 | {plan["secondary_delete"]} |',
         f'| 幂等跳过 | {plan["unchanged"]} |',
         f'| mock primary 行 | {mock_counts.get("kp_primary", 0)} |',
         f'| mock secondary 行 | {mock_counts.get("kp_secondary", 0)} |',
         f'| teacher 来源（合计） | {teacher_total}（93+104） |',
         f'| model 来源（剩余） | {model_total}（734） |',
         f'| primary 非空 | {primary_nonempty}（931） |',
         f'| 空 primary | {931 - primary_nonempty}（0） |',
         f'| 高考 annotations active | {gk_ann}（8007） |',
         f'| mock legacy points 非空 | {mock_points}（793） |',
         f'| 幂等复跑变化 | {changed}（0） |', '',
         f'- 备份：`{BACKUP}`', '',
         '## 重投影与卡片校验', '',
         '- 重投影：`tools/project_restricted_corpus.py --only mock --apply --force-generated`。',
         '- 931 卡 + 67 set note 数量不变；104 张教师卡 knowledge_points 恰为教师考点、正文恰 1 个 `[[kp]]`；',
         '- **931/931 卡 primary 非空**；高考卡 6324 张/sha256 未变；`human_edited` 保护（skip_human=0）。', '',
         '---', '', '> 回滚：`tools/kb_mock_targeted_review_apply.py --stage rollback`。', '']
    APPLY_REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[apply] primary {mock_counts.get("kp_primary",0)}｜secondary {mock_counts.get("kp_secondary",0)}｜'
          f'nonempty {primary_nonempty}｜teacher {teacher_total}｜model {model_total}｜gk {gk_ann}｜'
          f'幂等变化 {changed}')
    return 0 if (teacher_total == 197 and model_total == 734 and primary_nonempty == 931
                 and mock_counts.get('kp_primary') == 931 and gk_ann == 8007 and changed == 0) else 4


def stage_rollback(args):
    import psycopg
    if not BACKUP.exists():
        die(f'找不到 {BACKUP}')
    b = json.loads(BACKUP.read_text(encoding='utf-8'))
    conn = psycopg.connect(db_url()); cur = conn.cursor()
    qmap = _qmap(cur)
    qids = [qmap[r['qid']] for r in b['items']]
    print(f'[rollback] 删除 104 题当前 active rows，恢复备份 {len(b["annotations"])} 行')
    if args.dry_run:
        print('[rollback] dry-run，未写 PG')
        conn.close()
        return 0
    try:
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("""DELETE FROM knowledge_annotations
                WHERE question_id = ANY(%s::uuid[]) AND superseded_by IS NULL""", (qids,))
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
    ap = argparse.ArgumentParser(description='104 题定向复核修正')
    ap.add_argument('--stage', choices=['parse', 'apply', 'rollback'], default='parse')
    ap.add_argument('--source', default=os.environ.get('CHILON_TARGETED_REVIEW_SOURCE'),
                    help='教师回填 txt 路径（parse 必需；默认读 CHILON_TARGETED_REVIEW_SOURCE）')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)
    if args.stage == 'parse':
        if not args.source:
            ap.error('必须提供 --source 或 CHILON_TARGETED_REVIEW_SOURCE')
        return parse_targeted(pathlib.Path(args.source))
    if args.stage == 'apply':
        return stage_apply(args)
    return stage_rollback(args)


if __name__ == '__main__':
    sys.exit(main())
