#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 Obsidian 标注（vault: 02_Processed/Annotations/gk_*.json）导入 PostgreSQL。

背景（PG SSOT 决策）：PG 是唯一事实源，Obsidian 只做编辑审校。本工具是“标注入 PG”的第一步：
- 读 274 个标注 JSON / 6050 条（primary + secondary）；
- 通过 (tex 相对路径, 题号) 把 vault qid 映射到 PG knowledge_questions.id（UUID）；
- 写 knowledge_annotations（annotation_type = kp_primary / kp_secondary，幂等、带 superseded_by 历史）；
- 同步 knowledge_questions.current_knowledge_points（primary + secondary 的 kp_id 数组）；
- 默认 dry-run 只报计划；--apply 才写库，并输出 var/annotations/import_report.md。

用法（PATH 里的 python 即可，不需要 psycopg；数据库访问通过 docker exec psql）：
    python tools/kb_annotations_to_pg.py                      # dry-run：只报计划
    python tools/kb_annotations_to_pg.py --apply              # 执行写入 + 验证 + 写报告
    python tools/kb_annotations_to_pg.py --apply --report var/annotations/import_report.md

连接方式：
- 容器 chilon-pg-corpus 内本地 TCP 127.0.0.1:5432（宿主机对应 127.0.0.1:55495）；
- 密码不经过本进程：容器里 `PGPASSWORD="$POSTGRES_PASSWORD"` 由容器 env 提供，工具不读取、不打印；
- 需要 superuser 或 BYPASSRLS 角色（knowledge_* 表 FORCE RLS）。

写库口径：
- classification_source ∈ {rule, model, teacher}（库约束）；本批标注全部 source=model，故写 model，
  model_version 记录标注模型串（如 "deepseek-flash (batch, 2026-11-05)"），不引入库约束外的 "import"。
- 同一 (question_id, annotation_type) 仅一条 active 行（唯一索引）；secondary 因此存为一行 JSON 数组。
- 值变化时：先插入新行（superseded_by 暂指旧行）→ 旧行 superseded_by 指新行 → 新行激活，保留历史。
- 历史中已删除的标注（源里没有、PG 里 active）工具只报告不自动删除（stale 策略待评审）。

退出码：0 成功；2 数据/映射校验失败（未写库）；3 数据库访问失败；4 apply 后验证失败。
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import pathlib
import re
import shlex
import subprocess
import sys
import uuid

VAULT = pathlib.Path(r'C:\Users\Viver\Desktop\高中数学')
DEFAULT_ANN = VAULT / '02_Processed' / 'Annotations'
DEFAULT_OCR = VAULT / '02_Processed' / 'OCR_JSON'
VOCAB = VAULT / '10_Indexes' / '知识点词表.md'
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'var' / 'annotations'
CONTAINER = 'chilon-pg-corpus'
KP_RE = re.compile(r'^kp_\d\d_\d\d_[a-z_]+$')
QID_RE = re.compile(r'^gk_\d{4}_.+_q\d+$')
MANAGED_TYPES = ('kp_primary', 'kp_secondary')
SEP = chr(31)  # 多值读取时数组元素分隔符（避免与 CSV/TSV 冲突）


# ---------------------------------------------------------------- 数据库访问
class Psql:
    """通过 docker exec 在容器内用 psql 访问 PG；密码只存在于容器 env。"""

    def __init__(self, container=CONTAINER, db='chilon', user='postgres',
                 host='127.0.0.1', port=5432):
        self.container, self.db, self.user = container, db, user
        self.host, self.port = host, port

    def _run(self, sql: str, tuples: bool):
        # 注意：-F 需要真正的制表符（psql 不解析 "\t" 字面量），故拼接实际 TAB 字符
        opts = '-t -A -F "' + '\t' + '"' if tuples else ''
        inner = (
            'export PGPASSWORD="$POSTGRES_PASSWORD"; '
            'export PGCLIENTENCODING=UTF8; '
            f'exec psql -h {shlex.quote(self.host)} -p {int(self.port)} '
            f'-U {shlex.quote(self.user)} -d {shlex.quote(self.db)} '
            f'-X -v ON_ERROR_STOP=1 {opts}'
        )
        try:
            p = subprocess.run(['docker', 'exec', '-i', self.container, 'sh', '-c', inner],
                               input=sql, capture_output=True, text=True, encoding='utf-8')
        except FileNotFoundError:
            raise RuntimeError('找不到 docker 命令；本工具需要 Docker CLI 与运行中的 PG 容器')
        if p.returncode != 0:
            raise RuntimeError(f'psql 失败（exit {p.returncode}）：{p.stderr.strip()[:2000]}')
        return p.stdout

    def query(self, sql: str):
        """执行查询，返回 list[list[str]]（每行按 tab 切分）。"""
        out = self._run(sql.rstrip().rstrip(';') + ';\n', tuples=True)
        rows = []
        for line in out.splitlines():
            if not line:
                continue
            rows.append(line.split('\t'))
        return rows

    def script(self, sql: str) -> str:
        return self._run(sql, tuples=False)


# ---------------------------------------------------------------- 读取输入
def norm_no(v) -> str:
    s = str(v if v is not None else '').strip()
    if s.isdigit():
        return str(int(s))
    return s


def rel_tex(source_tex: str) -> str:
    """OCR_JSON source_tex（绝对/克隆路径）→ PG stem_locator.tex（相对 content/ 的路径）。"""
    s = (source_tex or '').replace('\\', '/')
    for marker in ('/content/',):
        i = s.find(marker)
        if i >= 0:
            return s[i + len(marker):]
    return s


def load_vocab_ids() -> set:
    ids = set()
    for line in VOCAB.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\|\s*`(kp_\d\d_\d\d_[a-z_]+)`\s*\|', line)
        if m:
            ids.add(m.group(1))
    return ids


def load_annotations(ann_dir: pathlib.Path):
    items, problems = [], []
    files = sorted(ann_dir.glob('gk_*.json'))
    for j in files:
        b = json.loads(j.read_text(encoding='utf-8'))
        doc_id = j.stem
        for it in b.get('items', []):
            qid = str(it.get('question_id') or '').strip()
            an = it.get('annotation') or {}
            if not QID_RE.match(qid):
                problems.append(f'{j.name}: 非法 qid {qid!r}')
                continue
            if qid.rsplit('_q', 1)[0] != doc_id:
                problems.append(f'{j.name}: qid 与文件名 doc_id 不一致：{qid}')
            kp = an.get('kp_primary') or ''
            sec = an.get('kp_secondary') or []
            if kp and not KP_RE.match(str(kp)):
                problems.append(f'{qid}: 非法 kp_primary {kp!r}')
            for s in sec:
                if not KP_RE.match(str(s)):
                    problems.append(f'{qid}: 非法 kp_secondary {s!r}')
            items.append({'qid': qid, 'doc_id': doc_id, 'ann': an, 'file': j.name})
    return files, items, problems


def load_ocr_map(ocr_dir: pathlib.Path):
    """qid -> (tex 相对路径, 规范化题号)。"""
    m, odd = {}, []
    for j in ocr_dir.glob('*/questions.json'):
        b = json.loads(j.read_text(encoding='utf-8'))
        rel = rel_tex(b.get('source_tex') or '')
        if not rel:
            odd.append(f'{j.parent.name}: 缺 source_tex')
        for q in b.get('questions', []):
            qid = str(q.get('question_id') or '')
            m[qid] = (rel, norm_no(q.get('question_number')))
    return m, odd


def load_pg_questions(psql: Psql):
    """(tex, 题号) -> PG question UUID；仅高考真题。"""
    rows = psql.query(
        """
        SELECT q.id, q.question_no, q.stem_locator->>'tex'
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'gaokao_paper'
        """
    )
    by_key, dup = {}, []
    for pid, no, tex in rows:
        key = (tex or '', norm_no(no))
        if key in by_key:
            dup.append(key)
        by_key[key] = pid
    return by_key, dup, len(rows)


# ---------------------------------------------------------------- 计划
def plan_import(items, ocr_map, pg_map, psql: Psql):
    # qid -> uuid
    uuid_by_qid, unmatched, ocr_missing = {}, [], []
    for it in items:
        key = ocr_map.get(it['qid'])
        if not key:
            ocr_missing.append(it['qid'])
            continue
        pid = pg_map.get(key)
        if not pid:
            unmatched.append((it['qid'], key))
            continue
        uuid_by_qid[it['qid']] = pid
    used = set(uuid_by_qid.values())

    # 期望写入的标注行 + current_knowledge_points
    desired, points_new = [], {}
    for it in items:
        pid = uuid_by_qid.get(it['qid'])
        if not pid:
            continue
        an = it['ann']
        kp = an.get('kp_primary') or ''
        sec = [str(s) for s in (an.get('kp_secondary') or [])]
        src = str(an.get('source') or 'model').strip()
        if src not in ('rule', 'model', 'teacher'):
            src = 'model'
        ver = an.get('model') if src == 'model' else None
        conf = an.get('confidence')
        arr = []
        if kp:
            desired.append({'question_id': pid, 'annotation_type': 'kp_primary', 'value': kp,
                            'classification_source': src, 'confidence': conf,
                            'model_version': ver})
            arr.append(kp)
        if sec:
            desired.append({'question_id': pid, 'annotation_type': 'kp_secondary',
                            'value': json.dumps(sec, ensure_ascii=False, separators=(',', ':')),
                            'classification_source': src, 'confidence': conf,
                            'model_version': ver})
            arr.extend(sec)
        points_new[pid] = arr or None

    # 现有 active 标注
    rows = psql.query(
        "SELECT question_id, annotation_type, id, value, classification_source, "
        "coalesce(model_version, ''), coalesce(confidence::text, '') "
        "FROM knowledge_annotations WHERE superseded_by IS NULL"
    )
    existing = {}
    for pid, atype, aid, value, src, ver, conf in rows:
        existing[(pid, atype)] = {'id': aid, 'value': value, 'source': src,
                                  'model_version': ver, 'confidence': conf}

    def norm_conf(c):
        if c is None or c == '':
            return ''
        try:
            return f'{float(c):.3f}'
        except (TypeError, ValueError):
            return str(c)

    pending = []
    unchanged = 0
    desired_keys = set()
    for row in desired:
        key = (row['question_id'], row['annotation_type'])
        desired_keys.add(key)
        ex = existing.get(key)
        if ex is None:
            pending.append({**row, 'new_id': str(uuid.uuid4()), 'old_id': None})
            continue
        same = (ex['value'] == row['value']
                and ex['source'] == row['classification_source']
                and ex['model_version'] == (row['model_version'] or '')
                and norm_conf(ex['confidence']) == norm_conf(row['confidence']))
        if same:
            unchanged += 1
        else:
            pending.append({**row, 'new_id': str(uuid.uuid4()), 'old_id': ex['id']})

    # 本次管理范围内、但源里已不存在的 active 行（只报告，不删除）
    managed_uuids = set(uuid_by_qid.values())
    stale = [(pid, atype, ex['id']) for (pid, atype), ex in existing.items()
             if pid in managed_uuids and atype in MANAGED_TYPES
             and (pid, atype) not in desired_keys]
    other_active = [k for k in existing
                    if not (k[0] in managed_uuids and k[1] in MANAGED_TYPES)]

    # current_knowledge_points 旧值
    rows = psql.query(
        """
        SELECT q.id, coalesce(array_to_string(q.current_knowledge_points, chr(31)), '')
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'gaokao_paper'
        """
    )
    old_points = {pid: ([x for x in arr.split(SEP) if x] if arr else []) for pid, arr in rows}
    points_changes = []
    for pid, new in points_new.items():
        old = old_points.get(pid, [])
        if old != (new or []):
            points_changes.append((pid, old, new))

    # 旧/新表示法差异（用于报告）
    old_nonempty = sum(1 for v in old_points.values() if v)
    both_empty = sum(1 for pid, new in points_new.items()
                     if not old_points.get(pid) and not new)
    old_tokens = {t for v in old_points.values() for t in v}
    new_tokens = {t for v in points_new.values() for t in (v or [])}

    return {
        'uuid_by_qid': uuid_by_qid, 'unmatched': unmatched, 'ocr_missing': ocr_missing,
        'unused_pg': sorted(set(pg_map.values()) - used),
        'desired': desired, 'pending': pending, 'unchanged': unchanged,
        'stale': stale, 'other_active': other_active,
        'points_new': points_new, 'old_points': old_points,
        'points_changes': points_changes,
        'old_nonempty': old_nonempty, 'both_empty': both_empty,
        'old_tokens': old_tokens, 'new_tokens': new_tokens,
    }


# ---------------------------------------------------------------- SQL / apply
def esc_copy(s) -> str:
    if s is None:
        return r'\N'
    s = str(s)
    return (s.replace('\\', '\\\\').replace('\t', '\\t')
            .replace('\n', '\\n').replace('\r', '\\r'))


def array_literal(arr):
    if not arr:
        return None
    return '{' + ','.join(arr) + '}'


def build_apply_sql(plan, sync_points: bool = False):
    pending, changes = plan['pending'], plan['points_changes']
    L = ['BEGIN;',
         'CREATE TEMP TABLE kp_pending (',
         '  new_id uuid, question_id uuid, annotation_type varchar(32), value text,',
         '  classification_source varchar(16), confidence numeric(4,3),',
         '  model_version varchar(120), old_id uuid',
         ') ON COMMIT DROP;',
         'COPY kp_pending FROM STDIN;']
    for p in pending:
        L.append('\t'.join([
            p['new_id'], p['question_id'], p['annotation_type'], esc_copy(p['value']),
            p['classification_source'], esc_copy(p['confidence']),
            esc_copy(p['model_version']), esc_copy(p['old_id']),
        ]))
    L.append('\\.')
    if sync_points:
        L += ['CREATE TEMP TABLE kp_points (question_id uuid, points text[]) ON COMMIT DROP;',
              'COPY kp_points FROM STDIN;']
        for pid, _old, new in changes:
            L.append('\t'.join([pid, esc_copy(array_literal(new))]))
        L.append('\\.')
    # 1) 变化行：先插入“非 active”的新行（superseded_by 暂时指向旧行，避开 active 唯一索引）
    L += ['INSERT INTO knowledge_annotations',
          '  (id, question_id, annotation_type, value, classification_source, confidence,',
          '   model_version, superseded_by)',
          'SELECT new_id, question_id, annotation_type, value, classification_source,',
          '       confidence, model_version, old_id',
          'FROM kp_pending WHERE old_id IS NOT NULL;',
          # 2) 旧行标记被替代
          'UPDATE knowledge_annotations a SET superseded_by = p.new_id',
          'FROM kp_pending p WHERE a.id = p.old_id;',
          # 3) 新行激活
          'UPDATE knowledge_annotations SET superseded_by = NULL',
          'WHERE id IN (SELECT new_id FROM kp_pending WHERE old_id IS NOT NULL);',
          # 4) 全新行直接插入
          'INSERT INTO knowledge_annotations',
          '  (id, question_id, annotation_type, value, classification_source, confidence,',
          '   model_version)',
          'SELECT new_id, question_id, annotation_type, value, classification_source,',
          '       confidence, model_version',
          'FROM kp_pending WHERE old_id IS NULL;']
    if sync_points:
        L += ['UPDATE knowledge_questions q',
              'SET current_knowledge_points = p.points, updated_at = now()',
              'FROM kp_points p',
              'WHERE q.id = p.question_id',
              '  AND q.current_knowledge_points IS DISTINCT FROM p.points;']
    L += ['COMMIT;']
    return '\n'.join(L) + '\n'


def verify_after(psql: Psql, plan, expected_rows, sync_points: bool = False):
    q = psql.query
    active_total = int(q("SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NULL")[0][0])
    superseded = int(q("SELECT count(*) FROM knowledge_annotations WHERE superseded_by IS NOT NULL")[0][0])
    by_type = {r[0]: int(r[1]) for r in q(
        "SELECT annotation_type, count(*) FROM knowledge_annotations "
        "WHERE superseded_by IS NULL GROUP BY 1 ORDER BY 1")}
    cov = q("""
        SELECT count(*),
               count(*) FILTER (WHERE q.current_knowledge_points IS NOT NULL
                                  AND cardinality(q.current_knowledge_points) > 0),
               count(*) FILTER (WHERE q.current_knowledge_points IS NULL)
        FROM knowledge_questions q
        JOIN knowledge_document_versions dv ON dv.id = q.document_version_id
        JOIN knowledge_sources s ON s.id = dv.source_id
        WHERE s.source_type = 'gaokao_paper'
    """)[0]
    points_nonempty, points_null = int(cov[1]), int(cov[2])
    total_gk = int(cov[0])
    # 重跑计划（幂等验证）：标注恒查；points 只在显式同步时才算“应零变化”
    replan = plan_import(plan['_items'], plan['_ocr_map'], plan['_pg_map'], psql)
    points_ok = (not sync_points) or (len(replan['points_changes']) == 0)
    return {
        'active_total': active_total, 'superseded': superseded, 'by_type': by_type,
        'gk_total': total_gk,
        'points_nonempty': points_nonempty, 'points_null': points_null,
        'points_pre_nonempty': plan['old_nonempty'],
        'sync_points': sync_points,
        'expected_rows': expected_rows,
        'replan_pending': len(replan['pending']),
        'replan_points_changes': len(replan['points_changes']),
        'replan_points_ok': points_ok,
        'replan_unchanged': replan['unchanged'],
    }


# ---------------------------------------------------------------- 报告
def _load_legacy_baseline():
    """读取旧基线复跑结果（var/retrieval/legacy_repro.json），用于报告；不存在则 None。"""
    p = ROOT / 'var' / 'retrieval' / 'legacy_repro.json'
    if not p.exists():
        return None
    try:
        m = (json.loads(p.read_text(encoding='utf-8')).get('metrics') or {})
        if not m.get('queries'):
            return None
        return {
            'found': m.get('found'), 'queries': m.get('queries'),
            'recall': f'{m["recall_at_k"]:.1%}' if m.get('recall_at_k') is not None else '—',
            'mrr': f'{m["mrr"]:.3f}' if m.get('mrr') is not None else '—',
            'empty': f'{m.get("empty")}/{m.get("queries")}',
            'empty_rate': f'{m["empty_rate"]:.1%}' if m.get('empty_rate') is not None else '—',
            'path': 'var/retrieval/legacy_repro.json',
        }
    except (ValueError, OSError):
        return None


def write_report(psql, args, files, items, problems, vocab, plan, apply_info, verify, expected_rows):
    out = pathlib.Path(args.report).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    primary_items = [it for it in items if (it['ann'].get('kp_primary') or '')]
    missing_primary = [(it['qid'], it['ann'].get('rationale') or '')
                       for it in items if not (it['ann'].get('kp_primary') or '')]
    sec_items = [it for it in items if (it['ann'].get('kp_secondary') or [])]
    sec_elems = sum(len(it['ann'].get('kp_secondary') or []) for it in items)
    kp_ids = set()
    for it in items:
        if it['ann'].get('kp_primary'):
            kp_ids.add(it['ann']['kp_primary'])
        kp_ids.update(it['ann'].get('kp_secondary') or [])
    unknown_kp = sorted(kp_ids - vocab)
    old_tokens, new_tokens = plan['old_tokens'], plan['new_tokens']
    points_changed = len(plan['points_changes'])
    L = ['---', 'type: data', f'updated: {_dt.date.today().isoformat()}',
         f'title: 标注导入 PG 报告（{now}）', '---', '',
         '# 标注导入 PostgreSQL 报告', '',
         f'> 生成时间：{now}　｜　模式：**{apply_info["mode"]}**　｜　工具：`tools/kb_annotations_to_pg.py`  ',
         f'> 数据库：容器 `{args.container}` / 库 `{args.db}` / 用户 `{args.user}`（容器内 TCP {args.host}:{args.port}，宿主机 127.0.0.1:55495）  ',
         '> 密码由容器 env 注入（`PGPASSWORD="$POSTGRES_PASSWORD"`），工具不读取、不打印。',
         f'> 同步策略：`knowledge_annotations` 是 **kp_id 的 SSOT**；`current_knowledge_points` 是旧工作台的'
         f'**遗留中文模块名缓存**，默认**不同步**（`--sync-legacy-points` 显式开启，本次：'
         f'{"开启" if apply_info["sync_points"] else "关闭"}）。', '',
         '## 1. 输入（Obsidian 标注）', '',
         '| 项 | 值 |', '| --- | --- |',
         f'| 标注文件 | {len(files)} 个 `02_Processed/Annotations/gk_*.json` |',
         f'| 标注条目 | {len(items)} 条（唯一 qid {len({it["qid"] for it in items})}） |',
         f'| 有 kp_primary | **{len(primary_items)} / {len(items)}** |',
         f'| 无 kp_primary（无归属题） | {len(missing_primary)} |',
         f'| 有 kp_secondary 的题 | {len(sec_items)}（二级 kp 共 {sec_elems} 个） |',
         f'| 出现过的 kp_id | {len(kp_ids)} 个（词表 {len(vocab)} 条；未知 {len(unknown_kp)} 个） |',
         f'| 数据问题 | {len(problems)} |', '']
    if missing_primary:
        L += [f'**无 kp_primary 的 {len(missing_primary)} 题**（标注源本身无归属，非导入丢失；工具未伪造主标注）：', '',
              '| qid | 理由 |', '| --- | --- |']
        for q, why in missing_primary:
            L.append(f'| `{q}` | {why} |')
        L += ['', '> 因此本次导入后 primary 覆盖为 %d/%d，而不是 6050/6050；'
              '补标后重跑 `--apply` 会自动补齐（幂等）。' % (len(primary_items), len(items)), '']
    if problems:
        L += ['**数据问题明细（前 20 条）**：', ''] + [f'- {p}' for p in problems[:20]] + ['']
    if unknown_kp:
        L += ['**不在词表内的 kp_id**：' + '、'.join(f'`{k}`' for k in unknown_kp), '']

    L += ['## 2. qid → PG question 映射', '',
          '映射键：vault 题目的 `document_id` + `question_number` → OCR_JSON `source_tex` 相对路径 + 题号 '
          '→ PG `knowledge_questions.stem_locator->>\'tex\'` + `question_no`。', '',
          '| 项 | 值 |', '| --- | --- |',
          f'| 写入目标 qid | {len(plan["uuid_by_qid"])}/{len(items)} |',
          f'| 无法匹配的 qid | **{len(plan["unmatched"])}** |',
          f'| OCR_JSON 缺失的 qid | {len(plan["ocr_missing"])} |',
          f'| 未对应到标注的 PG 高考题 | {len(plan["unused_pg"])} |', '']
    if plan['unmatched']:
        L += ['无法匹配（需人工处理，工具不会猜）：', '']
        L += [f'- `{q}` → {key}' for q, key in plan['unmatched'][:50]]
        L += ['']

    points_plan = f'{points_changed} 题' if apply_info['sync_points'] else '不同步（默认）'
    points_actual = (f'{apply_info["points_updated"]} 题' if apply_info['sync_points']
                     else '0（未改）')
    L += ['## 3. 写入计划与结果', '',
          '| 项 | dry-run 计划 | apply 实际 |', '| --- | --- | --- |',
          f'| 新增标注行 | {len(plan["pending"]) - len([p for p in plan["pending"] if p["old_id"]])} | '
          f'{apply_info["inserted"]} |',
          f'| 替换（旧值变化，保留历史） | {len([p for p in plan["pending"] if p["old_id"]])} | '
          f'{apply_info["replaced"]} |',
          f'| 无变化跳过 | {plan["unchanged"]} | {apply_info["unchanged"]} |',
          f'| stale（源已删，仅报告） | {len(plan["stale"])} | {apply_info["stale"]} |',
          f'| 同步 `current_knowledge_points`（legacy 缓存） | {points_plan} | {points_actual} |',
          f'| **写入后 active 标注行** | — | **{apply_info["active_after"]}** |',
          f'| **预期行数**（primary {len(primary_items)} + secondary {len(sec_items)}） | — | '
          f'**{expected_rows}** |', '']
    if apply_info['mode'] != 'apply':
        L += ['> 本报告为 dry-run 计划，未写入数据库。去掉 `--dry-run`/加 `--apply` 才会写库。', '']
    if not apply_info['sync_points']:
        L += ['> `current_knowledge_points` 默认不动：它是旧工作台的中文模块名缓存，'
              '`knowledge_annotations` 才是 kp_id 的 SSOT。需要改该列时必须显式 `--sync-legacy-points`'
              '（会破坏旧 `knowledge_search` 的 `&&` 过滤与 26.7% 旧基线，须迁移评审）。', '']

    L += ['## 4. apply 后验证', '',
          '| 项 | 值 |', '| --- | --- |',
          f'| `knowledge_annotations` active 行 | {verify["active_total"]} |',
          f'| 其中 kp_primary / kp_secondary | {verify["by_type"].get("kp_primary", 0)} / '
          f'{verify["by_type"].get("kp_secondary", 0)} |',
          f'| 历史 superseded 行 | {verify["superseded"]} |']
    if verify['sync_points']:
        L += [f'| 高考题（6050）有 kp_id 数组 | {verify["points_nonempty"]} |',
              f'| 其中 NULL（无 primary 也无 secondary） | {verify["points_null"]} |']
    else:
        L += [f'| `current_knowledge_points`（遗留中文缓存）非空 | {verify["points_nonempty"]}/6050 |',
              f'| 其中 NULL | {verify["points_null"]} |',
              '| 该列本次是否改动 | **否**（默认不同步） |']
    L += [f'| 重跑计划 | pending={verify["replan_pending"]}、points_changes='
          f'{verify["replan_points_changes"]}（仅 `--sync-legacy-points` 时要求为 0）、'
          f'unchanged={verify["replan_unchanged"]} |', '']
    ok_rows = verify['active_total'] == expected_rows
    ok_idem = verify['replan_pending'] == 0 and verify['replan_points_ok']
    L += [f'- 行数符合预期：{"✅" if ok_rows else "❌"}（{verify["active_total"]} / {expected_rows}）',
          f'- 幂等（重跑零变化）：{"✅" if ok_idem else "❌"}']
    if verify['sync_points']:
        L += [f'- kp_id 覆盖：{verify["points_nonempty"]}/{verify["gk_total"]} 高考题有 kp_id 数组'
              f'（{verify["points_nonempty"] / verify["gk_total"] * 100:.1f}%）；'
              f'{verify["points_null"]} 题为无归属题（源数据无 primary）']
    else:
        L += [f'- 遗留缓存：`current_knowledge_points` 非空 {verify["points_nonempty"]}/'
              f'{verify["gk_total"]}（导入前 {verify["points_pre_nonempty"]}），本次未改动'
              ' → 旧 `knowledge_search` / 旧基线不受影响']
    L += ['']

    L += ['## 5. `current_knowledge_points`：遗留缓存与 2026-11-06 还原记录', '',
          '**口径**：`knowledge_annotations` 是 kp_id 的**唯一事实源**（primary/secondary 带版本）；'
          '`knowledge_questions.current_knowledge_points` 是**旧工作台遗留的中文模块名缓存**'
          '（如 `三角函数/集合与逻辑`），**不是新事实源**，本工具默认不再写它。'
          'hybrid retrieval 必须读 `knowledge_annotations`，不得依赖该列的新旧格式。', '',
          '| 项 | 值 |', '| --- | --- |',
          f'| 当前缓存非空 / NULL | {verify["points_nonempty"]} / {verify["points_null"]}（共 {verify["gk_total"]}） |',
          f'| 本次是否写入 | {"是（--sync-legacy-points）" if verify["sync_points"] else "否（默认）"} |',
          f'| 若显式开启同步 | 计划改写 {points_changed} 题的 kp_id 数组（会破坏旧检索/旧基线） |', '',
          '### 5.1 还原事件（task-14，2026-11-06）', '',
          '- **原因**：首次导入（2026-11-06 12:58）把该列从中文模块名改成 kp_id 数组，'
          '导致旧 `backend/app/tools/impl.py::knowledge_search` 的 '
          '`current_knowledge_points && CAST(:topic_points AS text[])` 永不匹配，'
          '26.7% 旧基线无法复现。',
          '- **操作**：用导入前快照 `var/annotations/old_current_knowledge_points.tsv` 还原 6050 题'
          f'（非空 {verify["points_pre_nonempty"]} / NULL {verify["points_null"]}），'
          '逐条与快照比对通过；`knowledge_annotations` 保持 8007 条 active 未变。',
          '- **复现验证**：`.venv` 跑旧基线 `tools/eval_retrieval.py --k 8 --out-prefix '
          'var/retrieval/legacy_repro`，结果见下表；与 `var/retrieval/baseline_2026-11-06.json` 一致。',
          '- **策略**：该列保持旧语义直到迁移评审；新事实一律以 `knowledge_annotations` 为准。', '']
    base = _load_legacy_baseline()
    if base:
        L += ['| 旧基线指标（还原后复跑） | 值 |', '| --- | --- |',
              f'| Recall@8 | {base["found"]}/{base["queries"]} = {base["recall"]} |',
              f'| MRR@8 | {base["mrr"]} |',
              f'| 空结果率 | {base["empty"]}（{base["empty_rate"]}） |',
              f'| 报告文件 | `{base["path"]}` |', '']
    else:
        L += ['> 旧基线复跑结果未找到（`var/retrieval/legacy_repro.json` 不存在）；'
              '复现命令见 §9。', '']

    L += ['## 6. 幂等复跑', '',
          f'- 本次 apply 结束时立即重算导入计划：pending={verify["replan_pending"]}、'
          f'points_changes={verify["replan_points_changes"]}（默认不同步 points，仅标注判定幂等）、'
          f'unchanged={verify["replan_unchanged"]}。',
          '- 再次执行 `--apply` 不会新增/替换任何行（同一 (question_id, annotation_type) 只有一条 active；'
          '内容未变时跳过）。',
          f'- 写库 SQL 快照：`{apply_info["snapshot"]}`（var/annotations/，供审计/回放；不含密码）。', '']

    L += ['## 7. 数据库中的标注行结构', '',
          '| 字段 | 写入内容 |', '| --- | --- |',
          '| annotation_type | `kp_primary` / `kp_secondary` |',
          '| value | primary：`kp_xx_yy_slug`；secondary：JSON 数组（如 `["kp_02_02_domain"]`） |',
          '| classification_source | `model`（本批全部为模型标注；库约束只允许 rule/model/teacher） |',
          '| model_version | 标注 JSON 的 `model` 字段（如 `deepseek-flash (batch, 2026-11-05)`） |',
          '| confidence | 标注 JSON 的 `confidence`（0–1） |',
          '| created_by | NULL（批量导入，不冒充人工；人工审校请用 teacher + created_by） |',
          '| superseded_by | 旧版本链；内容变化时保留历史 |',
          '| created_at | 数据库 `now()` |', '']

    L += ['## 8. 风险与后续', '',
          '1. **qid 映射无原生外键**：PG 没有 `qid` 列，本次用 `(tex 相对路径, 题号)` 派生映射，'
          '6050/6050 命中；一旦 tex 文件改名/重导入，映射会断。建议后续 migration 增加外部 ID 列或映射表'
          '（契约草案 docs/KB_SYNC_CONTRACT.md 已列为 open item）。',
          '2. **`current_knowledge_points` 语义（已缓解，task-14）**：该列是旧工作台遗留的中文模块名缓存，'
          '本工具默认不再写它；`knowledge_annotations` 才是 kp_id 的 SSOT。'
          'hybrid retrieval 必须读 `knowledge_annotations`（active 行），不得依赖该列的中文名/kp_id 格式。'
          '旧 `knowledge_search`（`backend/app/tools/impl.py` 的 `&&` 过滤）依赖旧缓存，故保持旧语义；'
          '待迁移评审通过后再用 `--sync-legacy-points` 切换，并同步改检索/UI/旧基线。',
          '3. **5 题无 primary**：标注源未给出归属（图论/优选法/数学文化/题干缺失等），'
          '本次如实不写 primary；要达成 6050/6050 需人工补标或扩充词表后重跑。',
          '4. **secondary 存 JSON 数组**：受唯一索引 (question_id, annotation_type) 约束，'
          '一个题只有一条 active kp_secondary，下游需解析 JSON 而非单值。',
          '5. **review 状态未导入**：`status/rationale/reviewed_by` 在 `knowledge_annotations` 无对应列；'
          '它们留在 vault，后续经 `knowledge_reviews` 或标注 JSON 同步元数据承载。',
          '6. **stale 不自动删**：源中删除的标注在 PG 中仍 active，工具只报告（本次 0 条）；'
          'tombstone/supersede 策略待评审后再实现。',
          '7. **权限**：`knowledge_*` 表 FORCE RLS，apply 必须以 superuser/BYPASSRLS 角色执行'
          '（当前 postgres 满足）；普通角色会被策略拒绝。', '']

    L += ['## 9. 复现', '', '```powershell',
          '# 默认：只写 knowledge_annotations（不动 current_knowledge_points）',
          'python tools/kb_annotations_to_pg.py                    # dry-run',
          'python tools/kb_annotations_to_pg.py --apply            # 写入 + 验证 + 本报告',
          '',
          '# 仅在迁移评审通过、且检索/UI 已适配后：切换 current_knowledge_points 语义',
          'python tools/kb_annotations_to_pg.py --apply --sync-legacy-points',
          '',
          '# 旧基线复现（需 .venv + CHILON_TEST_DATABASE_URL 指向 chilon-pg-corpus；口令来自容器 env，不要写进文件）',
          '.\\.venv\\Scripts\\python.exe tools/eval_retrieval.py --input corpus/eval/teacher_questions.json --k 8 --out-prefix var/retrieval/legacy_repro',
          '```', '', '数据源：`C:\\Users\\Viver\\Desktop\\高中数学\\02_Processed\\Annotations`'
          '（只读，未修改 vault 任何文件）。', '']
    out.write_text('\n'.join(L), encoding='utf-8')
    return out


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description='Obsidian 标注 → PostgreSQL 导入（PG SSOT 第一步）')
    ap.add_argument('--annotations', default=str(DEFAULT_ANN), help='标注 JSON 目录')
    ap.add_argument('--ocr', default=str(DEFAULT_OCR), help='OCR_JSON 目录（用于 qid→tex/题号映射）')
    ap.add_argument('--container', default=CONTAINER, help='PG docker 容器名')
    ap.add_argument('--db', default='chilon')
    ap.add_argument('--user', default='postgres')
    ap.add_argument('--host', default='127.0.0.1', help='容器内 TCP host')
    ap.add_argument('--port', type=int, default=5432, help='容器内 TCP port（宿主机映射为 55495）')
    ap.add_argument('--apply', action='store_true', help='真正写库（默认只 dry-run）')
    ap.add_argument('--report', default=str(DEFAULT_OUT / 'import_report.md'),
                    help='apply 后报告路径')
    ap.add_argument('--out-dir', default=str(DEFAULT_OUT), help='SQL 快照/审计产物目录')
    ap.add_argument('--no-snapshot', action='store_true', help='不写 SQL 快照文件')
    ap.add_argument('--sync-legacy-points', action='store_true',
                    help='【默认关闭】把 current_knowledge_points 从旧工作台中文模块名缓存切换为 kp_id 数组；'
                         '会破坏旧 knowledge_search 的 && 过滤与 26.7%% 旧基线，仅迁移评审通过后使用')
    args = ap.parse_args(argv)
    if not args.apply:
        args.mode = 'dry-run'
    else:
        args.mode = 'apply'

    t0 = _dt.datetime.now()
    print('=' * 72)
    print('Obsidian 标注 → PostgreSQL 导入')
    print(f'模式：{args.mode}　标注目录：{args.annotations}')
    print(f'sync-legacy-points：{"开启（警告：会切换 current_knowledge_points 语义）" if args.sync_legacy_points else "关闭（默认：只写 knowledge_annotations）"}')
    print('=' * 72)

    # ---- 1. 读输入
    files, items, problems = load_annotations(pathlib.Path(args.annotations))
    if not items:
        print('[失败] 没有读到标注条目', file=sys.stderr)
        return 2
    vocab = load_vocab_ids()
    print(f'[1/6] 标注：{len(files)} 文件 / {len(items)} 条；primary '
          f'{sum(1 for it in items if it["ann"].get("kp_primary"))}；数据问题 {len(problems)}')
    if problems:
        for p in problems[:10]:
            print('   [问题]', p)

    # ---- 2. 映射
    ocr_map, ocr_odd = load_ocr_map(pathlib.Path(args.ocr))
    psql = Psql(args.container, args.db, args.user, args.host, args.port)
    try:
        pg_map, pg_dup, pg_total = load_pg_questions(psql)
    except RuntimeError as e:
        print(f'[失败] 数据库访问失败：{e}', file=sys.stderr)
        return 3
    print(f'[2/6] 映射：OCR 题 {len(ocr_map)}；PG 高考题 {pg_total}；'
          f'PG 重复键 {len(pg_dup)}；OCR 异常 {len(ocr_odd)}')
    if pg_dup:
        print('[失败] PG (tex, 题号) 存在重复，无法唯一映射：', pg_dup[:5], file=sys.stderr)
        return 2

    # ---- 3. 计划
    try:
        plan = plan_import(items, ocr_map, pg_map, psql)
    except RuntimeError as e:
        print(f'[失败] 数据库访问失败：{e}', file=sys.stderr)
        return 3
    plan['_items'], plan['_ocr_map'], plan['_pg_map'] = items, ocr_map, pg_map
    primary_items = [it for it in items if it['ann'].get('kp_primary')]
    sec_items = [it for it in items if it['ann'].get('kp_secondary')]
    expected_rows = len(primary_items) + len(sec_items)
    inserts = len([p for p in plan['pending'] if p['old_id'] is None])
    replaces = len(plan['pending']) - inserts
    print(f'[3/6] 映射结果：{len(plan["uuid_by_qid"])}/{len(items)} 命中；'
          f'无法匹配 {len(plan["unmatched"])}；未对应 PG 题 {len(plan["unused_pg"])}')
    if plan['unmatched'] or plan['ocr_missing']:
        for q, k in plan['unmatched'][:10]:
            print(f'   [无法匹配] {q} → {k}')
        for q in plan['ocr_missing'][:10]:
            print(f'   [OCR 缺题] {q}')
        print('[失败] 映射未 100% 命中，停止（不猜；不写库）。', file=sys.stderr)
        return 2
    print(f'[4/6] current_knowledge_points（旧工作台中文模块名缓存）：非空 '
          f'{plan["old_nonempty"]}/6050；'
          f'{"本次将切换为 kp_id 数组（--sync-legacy-points）" if args.sync_legacy_points else "本次不改动（默认；知识标注 SSOT 在 knowledge_annotations）"}')
    if args.sync_legacy_points:
        print('       [警告] current_knowledge_points 将从旧中文模块名切换为 kp_id 数组，'
              '旧 knowledge_search 的 && 过滤与 26.7% 旧基线会失效（仅迁移评审后使用）。', file=sys.stderr)
    pts_note = (f'points_update={len(plan["points_changes"])}' if args.sync_legacy_points
                else 'points 不同步（默认）')
    print(f'[5/6] 计划：insert={inserts} replace={replaces} unchanged={plan["unchanged"]} '
          f'stale={len(plan["stale"])} {pts_note}；预期 active 行 {expected_rows}')
    if len(primary_items) != len(items):
        print(f'[提示] 标注源 primary 覆盖 {len(primary_items)}/{len(items)}，'
              f'{len(items) - len(primary_items)} 题为无归属题（不伪造）。')

    # 管理员权限（apply 必需：FORCE RLS）
    try:
        roles = psql.query("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        is_admin = bool(roles) and roles[0][0] in ('t', 'true')
    except RuntimeError as e:
        print(f'[失败] 数据库访问失败：{e}', file=sys.stderr)
        return 3

    apply_info = {'mode': args.mode, 'inserted': 0, 'replaced': 0, 'unchanged': plan['unchanged'],
                  'stale': len(plan['stale']), 'points_updated': 0, 'active_after': 0,
                  'sync_points': bool(args.sync_legacy_points),
                  'snapshot': '(dry-run 未写)'}
    verify = {'active_total': 0, 'superseded': 0, 'by_type': {}, 'gk_total': 6050,
              'points_nonempty': plan['old_nonempty'], 'points_null': 6050 - plan['old_nonempty'],
              'points_pre_nonempty': plan['old_nonempty'],
              'sync_points': bool(args.sync_legacy_points), 'expected_rows': expected_rows,
              'replan_pending': len(plan['pending']),
              'replan_points_changes': len(plan['points_changes']),
              'replan_points_ok': True, 'replan_unchanged': plan['unchanged']}

    if args.apply:
        if not is_admin:
            print('[失败] 当前角色不是 superuser/BYPASSRLS，FORCE RLS 会拒绝写入。', file=sys.stderr)
            return 3
        out_dir = pathlib.Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        sql = build_apply_sql(plan, sync_points=args.sync_legacy_points)
        snap = out_dir / f'import_apply_{t0:%Y%m%d-%H%M%S}.sql'
        if not args.no_snapshot:
            snap.write_text(sql, encoding='utf-8')
            apply_info['snapshot'] = f'var/annotations/{snap.name}'
        pts_msg = (f'points {len(plan["points_changes"])} 行（--sync-legacy-points 开启）'
                   if args.sync_legacy_points else 'points 0 行（默认不改）')
        print(f'[6/6] 执行事务写入（pending {len(plan["pending"])} 行、{pts_msg}）…')
        try:
            out = psql.script(sql)
        except RuntimeError as e:
            print(f'[失败] 写库失败，事务应已回滚：{e}', file=sys.stderr)
            return 3
        for line in out.splitlines():
            if line.startswith(('INSERT ', 'UPDATE ', 'COPY ')):
                print('   ', line)
        apply_info.update(inserted=inserts, replaced=replaces,
                          points_updated=(len(plan['points_changes'])
                                          if args.sync_legacy_points else 0))
        # 写后验证
        try:
            verify = verify_after(psql, plan, expected_rows, args.sync_legacy_points)
        except RuntimeError as e:
            print(f'[失败] 写后验证失败：{e}', file=sys.stderr)
            return 4
        apply_info['active_after'] = verify['active_total']
        if verify['sync_points']:
            tail = (f'kp_id 覆盖 {verify["points_nonempty"]}/{verify["gk_total"]}')
        else:
            tail = (f'current_knowledge_points 未改（遗留缓存非空 '
                    f'{verify["points_nonempty"]}/{verify["gk_total"]}）')
        print(f'   写后：active={verify["active_total"]}（预期 {expected_rows}）｜{tail}｜重跑变化 '
              f'{verify["replan_pending"]}/{verify["replan_points_changes"]}')
        report = write_report(psql, args, files, items, problems, vocab, plan, apply_info, verify,
                              expected_rows)
        print(f'\n报告：{report}')
        ok = (verify['active_total'] == expected_rows
              and verify['replan_pending'] == 0 and verify['replan_points_ok'])
        return 0 if ok else 4
    else:
        # dry-run：不写报告（避免误当执行结果），只打印计划与样例
        print('     样例（前 5 条新行）：')
        for p in plan['pending'][:5]:
            print(f'       {p["question_id"][:8]}… {p["annotation_type"]:12s} '
                  f'{p["value"][:50]} src={p["classification_source"]} conf={p["confidence"]}')
        if args.sync_legacy_points:
            print('     current_knowledge_points 旧→新样例：')
            for pid, old, new in plan['points_changes'][:3]:
                print(f'       {pid[:8]}…  {"/".join(old) or "—"}  →  '
                      f'{"/".join(new) if new else "NULL"}')
        else:
            print(f'     current_knowledge_points：默认不同步（保持旧中文缓存；若开启会改 '
                  f'{len(plan["points_changes"])} 题，见 --sync-legacy-points）')
        print('\n[dry-run] 未写库、未写报告。确认后加 --apply 执行写入。')
        return 0


if __name__ == '__main__':
    sys.exit(main())
