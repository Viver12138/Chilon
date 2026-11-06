#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模拟题 100 题 pilot 标注的校验 + 报告生成工具（只读，不写 PG/vault）。

用途（task-22）：
- 校验 `var/mock_annotations/batch_100.txt` 与 `pilot_100.json`：
  100 行、qid 唯一且存在于 PG mock_exam 题、kp_id 全在 120 条词表、primary/secondary/confidence/rationale 合法；
- 生成 `var/mock_annotations/pilot_report.md`：
  分布（module/kp/question_type/confidence）、与 legacy 中文模块名的模块级一致率、
  Top 10 歧义、词表缺口、是否可全量的结论。

参数（均可环境变量提供）：
    --vault / CHILON_VAULT       vault 根（用于定位 10_Indexes/知识点词表.md）
    --vocab                     直接指定词表 md
    --database-url / CHILON_TEST_DATABASE_URL / CHILON_DATABASE_URL / 容器 env
                                 校验 qid 是否在 PG 中存在；--skip-db 可跳过
    --annotations-dir           默认 <repo>/var/mock_annotations
    --report                    默认 var/mock_annotations/pilot_report.md

用法（.venv，含 psycopg）：
    .\\.venv\\Scripts\\python.exe tools/kb_mock_annotate_validate.py --vault <vault>
    ... --skip-db --vocab <vault>/10_Indexes/知识点词表.md
退出码：0 通过；1 校验失败；2 参数/文件缺失；3 数据库不可用；4 缺依赖。
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

try:
    import psycopg  # type: ignore
except ImportError:  # pragma: no cover
    psycopg = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'var' / 'mock_annotations'
KP_RE = re.compile(r'^kp_\d\d_\d\d_[a-z_]+$')
QID_RE = re.compile(r'^mock_[0-9a-f-]{36}_q\d{2}$')
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'

# legacy current_knowledge_points 中文模块名 → 17 模块 id
LEGACY_MODULE = {
    '集合与逻辑': 'kp_01_set_logic', '函数': 'kp_02_function',
    '导数及其应用': 'kp_03_derivative', '三角函数': 'kp_04_trig',
    '解三角形': 'kp_04_trig', '平面向量': 'kp_05_vector', '复数': 'kp_06_complex',
    '数列': 'kp_07_sequence', '立体几何': 'kp_08_solid', '解析几何': 'kp_09_analytic',
    '概率与统计': 'kp_10_prob_stat', '计数原理': 'kp_11_counting',
    '不等式': 'kp_12_inequality', '算法初步': 'kp_14_algorithm',
    '平面几何选讲': 'kp_15_plane_geometry', '极限': 'kp_16_limit',
    '矩阵与变换': 'kp_17_matrix', '定积分': 'kp_18_integral',
}


def die(msg: str, code: int = 2):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(code)


def _db_url(database_url: str | None = None):
    if database_url:
        return database_url, '--database-url'
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
        raise RuntimeError('无法读取容器 env 密码；请用 --database-url 或设置环境变量')
    return (f'postgresql://{DB_USER}:{urllib.parse.quote(pw)}@{DB_HOST}:{DB_PORT}/{DB_NAME}',
            f'容器 {CONTAINER} env')


def load_vocab(path: pathlib.Path):
    ids, titles, modules = set(), {}, []
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+?)[（(].*?`(kp_\d\d_[a-z_]+)`', line)
        if m:
            modules.append((m.group(2), re.sub(r'^旧课标[，,]\s*', '', m.group(1)).strip()))
        m = re.match(r'\|\s*`(kp_\d\d_\d\d_[a-z_]+)`\s*\|\s*([^|]+)\|', line)
        if m:
            ids.add(m.group(1))
            titles[m.group(1)] = m.group(2).strip()
    return ids, titles, modules


def module_of(kp: str, modules) -> str:
    if not kp or not kp.startswith('kp_'):
        return ''
    num = kp.split('_')[1]
    return next((mid for mid, _ in modules if mid.split('_')[1] == num), '')


def parse_batch(path: pathlib.Path):
    rows = []
    for ln, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split('|')
        if len(parts) != 5:
            raise ValueError(f'batch 第 {ln} 行字段数 {len(parts)}（应为 5：qid|primary|secondary|confidence|rationale）')
        qid, primary, sec, conf, rationale = [x.strip() for x in parts]
        rows.append({'qid': qid, 'primary': primary, 'secondary': sec.split() if sec else [],
                     'confidence': conf, 'rationale': rationale, 'line': ln})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='模拟题 100 题 pilot 标注校验与报告')
    ap.add_argument('--vault', default=os.environ.get('CHILON_VAULT'),
                    help='vault 根目录（默认 CHILON_VAULT；用于定位词表）')
    ap.add_argument('--vocab', default=None, help='知识点词表 md（默认 <vault>/10_Indexes/知识点词表.md）')
    ap.add_argument('--database-url', default=None,
                    help='PG 连接串；默认 CHILON_TEST_DATABASE_URL → CHILON_DATABASE_URL → 容器 env')
    ap.add_argument('--skip-db', action='store_true', help='跳过 PG qid 存在性校验')
    ap.add_argument('--annotations-dir', default=str(DEFAULT_DIR))
    ap.add_argument('--report', default=None, help='报告输出路径（默认 <annotations-dir>/pilot_report.md）')
    args = ap.parse_args(argv)

    ann_dir = pathlib.Path(args.annotations_dir)
    batch_path = ann_dir / 'batch_100.txt'
    pilot_path = ann_dir / 'pilot_100.json'
    sample_path = ann_dir / 'sample_100.json'
    for p in (batch_path, pilot_path, sample_path):
        if not p.exists():
            die(f'缺少输入文件：{p}')

    vocab_path = pathlib.Path(args.vocab) if args.vocab else None
    if vocab_path is None:
        if not args.vault:
            die('需要 --vault 或 CHILON_VAULT（或直接 --vocab 指定词表）')
        vocab_path = pathlib.Path(args.vault) / '10_Indexes' / '知识点词表.md'
    if not vocab_path.exists():
        die(f'词表不存在：{vocab_path}')
    vocab, titles, modules = load_vocab(vocab_path)
    if len(vocab) != 120:
        die(f'词表条目 {len(vocab)}，应为 120')

    errors, warnings = [], []
    batch = parse_batch(batch_path)
    pilot = json.loads(pilot_path.read_text(encoding='utf-8'))
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    p_items = pilot.get('items', [])

    # ---- 结构校验
    if len(batch) != 100:
        errors.append(f'batch 行数 {len(batch)}，应为 100')
    if len(p_items) != 100:
        errors.append(f'pilot_100.json items 数 {len(p_items)}，应为 100')
    if len(sample.get('items', [])) != 100:
        errors.append(f'sample_100.json items 数 {len(sample.get("items", []))}，应为 100')

    qids = [r['qid'] for r in batch]
    dup = [q for q, c in collections.Counter(qids).items() if c > 1]
    if dup:
        errors.append(f'qid 重复：{dup[:5]}')
    for r in batch:
        if not QID_RE.match(r['qid']):
            errors.append(f'第 {r["line"]} 行 qid 格式异常：{r["qid"]}')
        if r['primary'] and not KP_RE.match(r['primary']):
            errors.append(f'{r["qid"]}：kp_primary 格式非法：{r["primary"]}')
        if r['primary'] and r['primary'] not in vocab:
            errors.append(f'{r["qid"]}：kp_primary 不在 120 词表：{r["primary"]}')
        if len(r['secondary']) > 2:
            errors.append(f'{r["qid"]}：secondary 超过 2 个：{r["secondary"]}')
        for s in r['secondary']:
            if s not in vocab:
                errors.append(f'{r["qid"]}：secondary 不在词表：{s}')
        if r['primary'] in r['secondary']:
            errors.append(f'{r["qid"]}：primary 出现在 secondary 中')
        try:
            conf = float(r['confidence'])
            if not (0.0 <= conf <= 1.0):
                raise ValueError
        except ValueError:
            errors.append(f'{r["qid"]}：confidence 非法：{r["confidence"]!r}')
        if not r['rationale']:
            errors.append(f'{r["qid"]}：rationale 为空')
        if not r['primary'] and float(r['confidence'] or 0) > 0.2:
            errors.append(f'{r["qid"]}：无 primary 但 confidence={r["confidence"]}（应≤0.2 并说明）')

    # ---- pilot 与 batch 一致性
    pilot_by_qid = {x['question_id']: x for x in p_items}
    if set(pilot_by_qid) != set(qids):
        errors.append('pilot_100.json 与 batch_100.txt 的 qid 集合不一致')
    for r in batch:
        x = pilot_by_qid.get(r['qid'])
        if not x:
            continue
        a = x.get('annotation') or {}
        if (a.get('kp_primary') or '') != r['primary']:
            errors.append(f'{r["qid"]}：pilot/batch primary 不一致')
        if list(a.get('kp_secondary') or []) != r['secondary']:
            errors.append(f'{r["qid"]}：pilot/batch secondary 不一致')
        if float(a.get('confidence') if a.get('confidence') is not None else -1) != float(r['confidence']):
            errors.append(f'{r["qid"]}：pilot/batch confidence 不一致')
        if (a.get('rationale') or '') != r['rationale']:
            errors.append(f'{r["qid"]}：pilot/batch rationale 不一致')
        if a.get('status') != 'needs_review' or a.get('source') != 'model':
            errors.append(f'{r["qid"]}：annotation.status/source 应为 needs_review/model')

    # ---- sample 与 batch 的 qid 一致
    if set(x['question_id'] for x in sample.get('items', [])) != set(qids):
        errors.append('sample_100.json 与 batch_100.txt 的 qid 集合不一致')
    # 每套 ≤2 校验
    per_set = collections.Counter(x['source_id'] for x in sample.get('items', []))
    bad_sets = {k: v for k, v in per_set.items() if v > 2}
    if bad_sets:
        errors.append(f'抽样每套 >2：{bad_sets}')

    # ---- PG qid 存在性
    db_label = None
    if not args.skip_db:
        if psycopg is None:
            die('缺少 psycopg：请用 .venv 运行（或 --skip-db 只做结构校验）', code=4)
        try:
            url, db_label = _db_url(args.database_url)
            conn = psycopg.connect(url)
            cur = conn.cursor()
            cur.execute("""
                SELECT s.id::text, q.question_no
                FROM knowledge_chunks c
                JOIN knowledge_document_versions dv ON dv.id = c.document_version_id
                JOIN knowledge_sources s ON s.id = dv.source_id
                JOIN knowledge_questions q
                  ON q.document_version_id = c.document_version_id AND q.stem_locator = c.locator
                WHERE s.source_type = 'mock_exam'
            """)
            db_qids = {f'mock_{sid}_q{int(no):02d}' for sid, no in cur.fetchall()}
            conn.close()
        except Exception as e:  # noqa: BLE001
            die(f'数据库校验失败：{type(e).__name__}: {e}', code=3)
        if len(db_qids) != 931:
            warnings.append(f'PG mock qid 数 {len(db_qids)}（预期 931）')
        missing = [q for q in qids if q not in db_qids]
        if missing:
            errors.append(f'{len(missing)} 个 qid 不在 PG mock 题中：{missing[:5]}')

    # ---- 指标
    rows = []
    for r in batch:
        x = pilot_by_qid.get(r['qid'], {})
        r = dict(r)
        r['module'] = module_of(r['primary'], modules)
        r['legacy_modules_raw'] = x.get('legacy_modules') or []
        r['legacy_module_ids'] = sorted({LEGACY_MODULE[m] for m in r['legacy_modules_raw']
                                         if m in LEGACY_MODULE})
        r['unknown_legacy'] = [m for m in r['legacy_modules_raw'] if m not in LEGACY_MODULE]
        r['question_type'] = x.get('question_type')
        r['set_title'] = x.get('set_title')
        rows.append(r)

    primary_n = sum(1 for r in rows if r['primary'])
    no_primary = [r for r in rows if not r['primary']]
    sec_n = sum(len(r['secondary']) for r in rows)
    sec_any = sum(1 for r in rows if r['secondary'])
    confs = [float(r['confidence']) for r in rows if r['primary']]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    legacy_rows = [r for r in rows if r['primary'] and r['legacy_module_ids']]
    legacy_ok = sum(1 for r in legacy_rows if r['module'] in r['legacy_module_ids'])
    legacy_rate = (legacy_ok / len(legacy_rows) * 100) if legacy_rows else 0.0
    legacy_mismatch = [(r, [titles.get(k, k) for k in r['legacy_module_ids']]) for r in legacy_rows
                       if r['module'] not in r['legacy_module_ids']]
    no_legacy = [r for r in rows if not r['legacy_module_ids'] and r['primary']]
    empty_legacy_we_annotated = [r for r in rows if not r['legacy_modules_raw'] and r['primary']]

    by_module = collections.Counter(r['module'] for r in rows if r['module'])
    by_kp = collections.Counter(r['primary'] for r in rows if r['primary'])
    by_type = collections.Counter(str(r['question_type']) for r in rows)
    by_sec = collections.Counter(len(r['secondary']) for r in rows)
    conf_buckets = collections.Counter()
    for r in rows:
        if not r['primary']:
            conf_buckets['无归属'] += 1
            continue
        c = float(r['confidence'])
        conf_buckets['<0.70' if c < 0.7 else '0.70–0.79' if c < 0.8 else '0.80–0.89' if c < 0.9 else '≥0.90'] += 1

    # ---- 歧义：低置信 / 无归属 / OCR 块污染 / 跨模块工具
    def ambiguity_reason(r):
        rs = []
        if not r['primary']:
            rs.append('无归属')
        elif float(r['confidence']) <= 0.7:
            rs.append('低置信')
        if any(k in r['rationale'] for k in ('块含', '残缺', 'OCR')):
            rs.append('OCR 块污染/残缺')
        if r['secondary']:
            rs.append('有工具性 secondary')
        return '｜'.join(rs) or '—'

    ambiguous = [r for r in rows if (not r['primary']) or float(r['confidence']) <= 0.7
                 or any(k in r['rationale'] for k in ('块含', '残缺', 'OCR'))]
    ambiguous.sort(key=lambda r: (r['primary'] != '', float(r['confidence'])))
    top_amb = ambiguous[:10]

    # 词表缺口 vs 题目质量问题
    vocab_gap = [r for r in no_primary if any(k in r['rationale'] for k in ('词表', '缺口'))]
    data_gap = [r for r in no_primary if r not in vocab_gap]

    # 模块级跨模块（primary 模块不在 legacy 集合，且 legacy 非空）
    cross = [r for r in legacy_mismatch]

    # 判断是否可全量（数据驱动阈值）
    can_full = (not errors and primary_n / 100 >= 0.9 and len(vocab_gap) <= 3)
    conclusion = ('可以全量 931 题，但先做三件事（见 §5）：清洗/切分 OCR 块、'
                  '补 2 类词表缺口或明确留空规则、把多问综合题口径写死。'
                  if can_full else '暂不建议直接全量：先修口径/词表/OCR 块再扩大样本。')

    # ---- 输出报告
    report_path = pathlib.Path(args.report) if args.report else ann_dir / 'pilot_report.md'
    L = ['---', 'type: report', 'title: 模拟题 100 题 pilot 标注报告', 'updated: 2026-11-06',
         'status: pilot', '---', '',
         '# 模拟题 100 题 pilot 标注报告（不碰 OCR、不写 PG）', '',
         f'> 抽样：seed `{sample.get("seed")}`，从 PG `mock_exam` 67 套 / 931 chunks 中抽 '
         f'**{len(rows)} 题**（每套 ≤2，覆盖各题型）。规则：{sample.get("rule")}  ',
         '> qid 清单：`var/mock_annotations/sample_100.json` / `batch_100.txt`。', '',
         '## 1. 校验结果', '',
         f'| 项 | 结果 |', '| --- | --- |',
         f'| batch 行数 / pilot 条目 | {len(batch)} / {len(p_items)} |',
         f'| qid 唯一 | {"✅" if not dup else "❌ " + str(dup[:3])} |',
         f'| PG mock qid 存在性 | {"✅ 全部存在" if not args.skip_db and not any("不在 PG" in e for e in errors) else "已跳过/异常"} |',
         f'| kp_id 全部在 120 词表 | {"✅" if not any("不在" in e and "词表" in e for e in errors) else "❌"} |',
         f'| primary 非空率 | **{primary_n}/100 = {primary_n:.0f}%** |',
         f'| secondary 个数分布 | {dict(sorted(by_sec.items()))}（共 {sec_n} 个） |',
         f'| 错误数 | **{len(errors)}** |',
         f'| 警告数 | {len(warnings)} |', '']
    if errors:
        L += ['**错误清单**（前 30 条）：', ''] + [f'- {e}' for e in errors[:30]] + ['']
    if warnings:
        L += ['**警告**：', ''] + [f'- {w}' for w in warnings] + ['']

    L += ['## 2. 100 题分布', '',
          '### 2.1 按模块（primary 折算）', '',
          '| 模块 | 题数 |', '| --- | --- |']
    for mid, cnt in by_module.most_common():
        L.append(f'| {dict((m, n) for m, n in modules)[mid]} | {cnt} |')
    L += ['', '### 2.2 按具体考点（Top 15）', '',
          '| kp_id | 名称 | 题数 |', '| --- | --- | --- |']
    for kp, cnt in by_kp.most_common(15):
        L.append(f'| `{kp}` | {titles.get(kp, kp)} | {cnt} |')
    L += ['', '### 2.3 按题型', '', '| question_type | 题数 |', '| --- | --- |']
    for t, cnt in sorted(by_type.items()):
        L.append(f'| {t if t != "None" else "未分类（PG 为 NULL）"} | {cnt} |')
    L += ['', '### 2.4 置信度分布', '', '| 区间 | 题数 |', '| --- | --- |']
    for b in ('≥0.90', '0.80–0.89', '0.70–0.79', '<0.70', '无归属'):
        if conf_buckets.get(b):
            L.append(f'| {b} | {conf_buckets[b]} |')
    L += ['', f'- 平均置信度（不含无归属）：**{avg_conf:.3f}**', '']

    L += ['## 3. 与 legacy 中文模块名的模块级一致率（参考，不是验收）', '',
          f'- 比对范围：有 primary 且 legacy 非空 = **{len(legacy_rows)}/100** 题',
          f'- **模块级一致：{legacy_ok}/{len(legacy_rows)} = {legacy_rate:.1f}%**',
          '- legacy 来源：PG `knowledge_questions.current_knowledge_points`（旧 tex taxonomy 中文模块名，未核验）；'
          '归一化映射见工具 `tools/kb_mock_annotate_validate.py`。',
          f'- 我们标了 primary 但 legacy 为空：{len(empty_legacy_we_annotated)} 题（旧模块名为缺失/未覆盖）', '']
    if legacy_mismatch:
        L += ['**模块级不一致明细**：', '',
              '| qid | 我们的 primary | 我们的模块 | legacy 模块 | 置信 |', '| --- | --- | --- | --- | --- |']
        for r, names in legacy_mismatch:
            L.append(f'| `{r["qid"]}` | `{r["primary"]}` | {dict((m, n) for m, n in modules)[r["module"]]} | '
                     f'{" / ".join(names)} | {r["confidence"]} |')
        L += ['']
    if not args.skip_db and db_label:
        L += [f'> DB 校验来源：{db_label}（只读，未写 PG）。', '']

    L += ['## 4. Top 10 歧义题（低置信 / 无归属 / OCR 块污染）', '',
          '| # | qid | 题目类型 | primary | 置信 | 原因 | 判读依据 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for n, r in enumerate(top_amb, 1):
        L.append(f'| {n} | `{r["qid"]}` | {r["question_type"] or "NULL"} | '
                 f'{("`" + r["primary"] + "`") if r["primary"] else "（留空）"} | {r["confidence"]} | '
                 f'{ambiguity_reason(r)} | {r["rationale"]} |')
    L += ['', '### 4.1 歧义分类', '',
          f'- 无归属：{len(no_primary)} 题（词表缺口 {len(vocab_gap)}、题干 OCR 残缺/信息不足 {len(data_gap)}）',
          f'- 低置信（≤0.70）：{sum(1 for r in rows if r["primary"] and float(r["confidence"]) <= 0.7)} 题',
          f'- OCR 块含相邻题/残缺：{sum(1 for r in rows if any(k in r["rationale"] for k in ("块含", "残缺", "OCR")))} 题',
          f'- 带工具性 secondary：{sec_any} 题（共 {sec_n} 个次标签）', '']

    L += ['## 5. 词表缺口与题目质量问题', '',
          '### 5.1 词表缺口（建议补词条或明确留空规则）', '']
    if vocab_gap:
        for r in vocab_gap:
            L.append(f'- `{r["qid"]}`：{r["rationale"]}')
    else:
        L.append('- 无。')
    L += ['', '### 5.2 题目/OCR 质量问题（本 pilot 不碰 OCR，全量前应清洗）', '']
    if data_gap:
        for r in data_gap:
            L.append(f'- `{r["qid"]}`：{r["rationale"]}')
    else:
        L.append('- 无。')
    contaminated = [r for r in rows if any(k in r['rationale'] for k in ('块含', '残缺', 'OCR'))]
    if contaminated:
        L += ['', f'共 {len(contaminated)} 题块含相邻题/残缺（见列表）：', '']
        L += [f'- `{r["qid"]}`（{r["set_title"]}）' for r in contaminated]

    L += ['', '## 6. 结论：是否可全量 931 题', '',
          f'- 有效 primary：**{primary_n}/100（{primary_n:.0f}%）**；无归属 {len(no_primary)} 题'
          f'（词表缺口 {len(vocab_gap)}、题干问题 {len(data_gap)}）。',
          f'- legacy 模块级一致率：**{legacy_rate:.1f}%**（{legacy_ok}/{len(legacy_rows)}，仅参考）。',
          f'- 平均置信度 {avg_conf:.3f}；低置信（≤0.70）{sum(1 for r in rows if r["primary"] and float(r["confidence"]) <= 0.7)} 题。',
          '',
          f'**{conclusion}**', '',
          '前置修正建议：',
          '1. **OCR 块清洗/切分**：pilot 中有 ' + str(len(contaminated)) +
          ' 题 chunk 含相邻题或题干残缺；全量前需按题号重新切分（本轮不碰 OCR，只记录问题）。',
          '2. **词表缺口**：' + ('补「隐函数/曲线与方程」「三维旋转曲面/椭球面」相关词条，或明确这类题 primary 留空的规则；'
                                if vocab_gap else '无。'),
          '3. **口径写死**：多问综合题按命题意图取 primary（如导数综合取零点/切线），工具性内容进 secondary；'
          'chunk 含相邻题时按该 chunk 的题号（首题）标注，并在 rationale 注明。',
          '4. **全量节奏**：931 题可沿用同口径模型标注 + 人工抽检 10%（约 93 题）+ 分歧复核；'
          '但必须先解决 OCR 块污染，否则 qid↔题干对应错误会污染全量标注。', '',
          '---', '',
          f'> 生成：`tools/kb_mock_annotate_validate.py`；数据：`{batch_path.name}`、`{pilot_path.name}`、'
          f'`{sample_path.name}`；本报告不写 PG/vault。', '']
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('\n'.join(L), encoding='utf-8')

    print('=' * 72)
    print('模拟题 100 题 pilot 标注校验')
    print('=' * 72)
    print(f'batch: {len(batch)} 行｜pilot: {len(p_items)} 条｜primary {primary_n}/100｜'
          f'无归属 {len(no_primary)}（词表缺口 {len(vocab_gap)}、题干 {len(data_gap)}）')
    print(f'legacy 模块级一致：{legacy_ok}/{len(legacy_rows)} = {legacy_rate:.1f}%'
          f'（参考；legacy 非空 {len(legacy_rows)}）')
    print(f'secondary: {sec_any} 题 / {sec_n} 个｜平均置信 {avg_conf:.3f}｜'
          f'低置信 {sum(1 for r in rows if r["primary"] and float(r["confidence"]) <= 0.7)} 题')
    print(f'错误 {len(errors)} 条；报告：{report_path}')
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
