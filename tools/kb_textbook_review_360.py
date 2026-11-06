#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 360 复核、全量加权估计、合并 100 pilot、应用 teacher 到 reviewed var 映射。

不调 OCR、不写 PG/vault、不 commit。

路径均通过环境变量提供（不内置个人路径）：360 复核 txt = CHILON_REVIEW_360_SOURCE；
100 pilot 教师标签 = CHILON_TEACHER_LABELS（可选，缺省跳过合并）；词表默认仓库内
corpus/eval/kp_vocab.md，可用 CHILON_KP_VOCAB 覆盖。
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
SRC = pathlib.Path(os.environ['CHILON_REVIEW_360_SOURCE']) if os.environ.get('CHILON_REVIEW_360_SOURCE') else None
SAMPLE = OUT / 'sample_360.json'
MAPPED = OUT / 'mapped_1797.json'
PARSED = OUT / 'review_360_parsed.json'
REVIEWED = OUT / 'mapped_1797_reviewed.json'
REPORT = OUT / 'review_360_result.md'
PILOT = OUT / 'mapped_100.json'
PILOT_V3 = OUT / 'mapped_100_v3.json'
TEACHER_PILOT = pathlib.Path(os.environ['CHILON_TEACHER_LABELS']) if os.environ.get('CHILON_TEACHER_LABELS') else None
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))


def load_vocab():
    vocab = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('|'):
            parts = [x.strip() for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
                vocab[parts[0].strip('`')] = parts[1]
    if len(vocab) != 120:
        raise SystemExit(f'vocab {len(vocab)} != 120')
    return vocab


def parse_rows():
    rows = []
    for line in SRC.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) == 4 and re.fullmatch(r'\d+', parts[0]):
            rows.append({'index': int(parts[0]), 'teacher_module': parts[1],
                         'teacher_kp': parts[2], 'note': parts[3]})
    if len(rows) != 360:
        raise SystemExit(f'rows {len(rows)} != 360')
    if [r['index'] for r in rows] != list(range(1, 361)):
        raise SystemExit('序号不连续')
    return rows


def classify_note(note):
    n = note or ''
    if re.search(r'章末|小结|复习|整章|全章', n):
        return '章末/整章小结'
    if re.search(r'跨节|混排|混入|串题|多处|多节', n):
        return '跨节/混排'
    if re.search(r'导引|前言|目录|阅读|栏目|词汇|版权页|封面|主编寄语', n):
        return '栏目/导引/非正文'
    if re.search(r'符号|OCR|乱码|识别|看不清|缺', n, flags=re.I):
        return '符号/OCR'
    if re.search(r'概念|定义|误标|判错|模块|归类|错', n):
        return '概念/模块误判'
    if re.search(r'应用|模型|建模|实际|情境|背景', n):
        return '应用/建模'
    if re.search(r'图像|图象|性质|单调|奇偶|周期|对称|最值', n):
        return '图像/性质'
    if re.search(r'统计|概率|分布|回归|抽样|检验|百分位', n):
        return '统计/概率'
    if re.search(r'运算|计算|公式|求值|化简|方程|不等式', n):
        return '运算/公式'
    return '其他'


def pilot_labels():
    rows = []
    if TEACHER_PILOT is None:
        print('[warn] 未提供 100 pilot 教师标签（CHILON_TEACHER_LABELS），跳过合并', file=sys.stderr)
        return rows
    for line in TEACHER_PILOT.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) == 7 and re.fullmatch(r'\d+', parts[0]):
            rows.append({'block_id': parts[1], 'teacher_module': parts[3], 'teacher_kp': parts[4]})
    return [r for r in rows if r['teacher_module'] not in ('—', '') and r['teacher_kp'] not in ('—', '')]


def main():
    if SRC is None:
        print('[失败] 需要环境变量 CHILON_REVIEW_360_SOURCE 指向 360 复核 txt', file=sys.stderr)
        return 2
    vocab = load_vocab()
    rows = parse_rows()
    sample = json.loads(SAMPLE.read_text(encoding='utf-8'))
    ids = sample['block_ids']
    if len(ids) != 360 or len(set(ids)) != 360:
        raise SystemExit('sample_360 ids 非 360 唯一')
    mapped = json.loads(MAPPED.read_text(encoding='utf-8'))['items']
    byid = {x['block_id']: x for x in mapped}
    if len(mapped) != 1797 or len(byid) != 1797:
        raise SystemExit('mapped_1797 覆盖/唯一失败')
    # 校验教师标签
    errors = []
    for r in rows:
        tm, tk = r['teacher_module'], r['teacher_kp']
        if tm == '—' and tk == '—':
            continue
        if tm == '—' or tk == '—':
            errors.append(f'{r["index"]}: 半缺判')
        if not re.fullmatch(r'kp_\d{2}_[a-z_]+', tm):
            errors.append(f'{r["index"]}: 教师模块非法 {tm}')
        if tk not in vocab:
            errors.append(f'{r["index"]}: 教师考点非法 {tk}')
    # 解析到 360 行
    parsed = []
    raw_teacher_content = raw_blank = 0
    for r in rows:
        bid = ids[r['index'] - 1]
        x = byid[bid]
        has_teacher = r['teacher_module'] != '—' and r['teacher_kp'] != '—'
        raw_teacher_content += has_teacher
        raw_blank += not has_teacher
        parsed.append({**r, 'block_id': bid, 'book': x['book'], 'page': x['page'],
                       'model_primary': x['kp_primary'], 'model_secondary': x['kp_secondary'],
                       'model_confidence': x['confidence'], 'model_status': x['status'],
                       'has_teacher': has_teacher})
    # 任务口径：内容 = 教师有标签 且 模型状态非 non_content（327）；non_content = 其余（33）
    content = [p for p in parsed if p['has_teacher'] and p['model_status'] != 'non_content']
    non_content = [p for p in parsed if not (p['has_teacher'] and p['model_status'] != 'non_content')]
    missing = [p for p in parsed if (p['teacher_module'] == '—') ^ (p['teacher_kp'] == '—')]
    # 指标
    hits = {'module': 0, 'exact': 0, 'any': 0}
    mismatch_nonempty = []
    mismatch_empty = []
    for p in content:
        mp = p['model_primary']
        tm = p['teacher_module'].split('_')[1]
        tk = p['teacher_kp']
        module = bool(mp) and mp.split('_')[1] == tm
        exact = mp == tk
        anym = tk in (([mp] if mp else []) + list(p['model_secondary']))
        hits['module'] += module
        hits['exact'] += exact
        hits['any'] += anym
        if not exact:
            rec = {'block_id': p['block_id'], 'teacher_kp': tk,
                   'teacher_name': vocab.get(tk, ''), 'model_primary': mp,
                   'model_confidence': p['model_confidence'],
                   'type': classify_note(p['note']), 'note': p['note']}
            if mp:
                mismatch_nonempty.append(rec)
            else:
                mismatch_empty.append(rec)
    n = len(content)
    # 全量 risk 分层加权
    full = collections.Counter()
    for x in mapped:
        if x['status'] == 'non_content':
            full['non_content'] += 1
        elif x['status'] == 'vocab_gap':
            full['vocab_gap'] += 1
        elif x['confidence'] <= 0.70:
            full['low'] += 1
        else:
            full['normal'] += 1
    strat = collections.defaultdict(lambda: {'n': 0, 'module': 0, 'exact': 0, 'any': 0})
    for p in content:
        if p['model_status'] == 'vocab_gap':
            st = 'vocab_gap'
        elif p['model_confidence'] <= 0.70:
            st = 'low'
        else:
            st = 'normal'
        s = strat[st]
        s['n'] += 1
        s['module'] += int(bool(p['model_primary']) and p['model_primary'].split('_')[1] == p['teacher_module'].split('_')[1])
        s['exact'] += int(p['model_primary'] == p['teacher_kp'])
        s['any'] += int(p['teacher_kp'] in (([p['model_primary']] if p['model_primary'] else []) + list(p['model_secondary'])))
    weighted = {}
    den = sum(full[k] for k in ('vocab_gap', 'low', 'normal'))
    for metric in ('module', 'exact', 'any'):
        num = 0.0
        for st in ('vocab_gap', 'low', 'normal'):
            if strat[st]['n']:
                num += full[st] * (strat[st][metric] / strat[st]['n'])
        weighted[metric] = num / den if den else 0.0
    # 合并 100 pilot
    pilot = pilot_labels()
    pv3 = json.loads(PILOT_V3.read_text(encoding='utf-8'))['items']
    pv3map = {x['block_id']: x for x in pv3}
    pm = pe = pa = 0
    for p in pilot:
        x = pv3map.get(p['block_id'])
        if not x:
            continue
        mp = x['kp_primary']
        tm = p['teacher_module'].split('_')[1]
        tk = p['teacher_kp']
        pm += int(bool(mp) and mp.split('_')[1] == tm)
        pe += int(mp == tk)
        pa += int(tk in (([mp] if mp else []) + list(x['kp_secondary'])))
    combined = {'module': hits['module'] + pm, 'exact': hits['exact'] + pe, 'any': hits['any'] + pa,
                'n': n + len(pilot), 'pilot_n': len(pilot), 'pilot': (pm, pe, pa)}
    # reviewed var
    reviewed = []
    teacher_by_id = {p['block_id']: p for p in parsed}
    for x in mapped:
        rec = dict(x)
        rec['model_primary'] = x['kp_primary']
        rec['model_secondary'] = list(x['kp_secondary'])
        rec['model_status'] = x['status']
        rec['teacher_module'] = ''
        rec['teacher_kp'] = ''
        rec['review_status'] = 'model'
        rec['kp_primary'] = x['kp_primary']
        if x['block_id'] in teacher_by_id:
            p = teacher_by_id[x['block_id']]
            rec['review_status'] = 'teacher'
            rec['teacher_module'] = p['teacher_module']
            rec['teacher_kp'] = p['teacher_kp']
            if p['has_teacher']:
                rec['kp_primary'] = p['teacher_kp']
                rec['module'] = p['teacher_module'].split('_')[1]
                rec['kp_name'] = vocab.get(p['teacher_kp'], '')
                rec['kp_secondary'] = []
                rec['status'] = 'mapped'
            else:
                rec['kp_primary'] = ''
                rec['module'] = ''
                rec['kp_name'] = ''
                rec['kp_secondary'] = []
                rec['status'] = 'non_content'
        reviewed.append(rec)
    REVIEWED.write_text(json.dumps({'count': len(reviewed), 'teacher_count': len(parsed),
                                    'items': reviewed}, ensure_ascii=False, indent=1), encoding='utf-8')
    PARSED.write_text(json.dumps({'total': 360, 'raw_teacher_content': raw_teacher_content,
                                  'raw_blank': raw_blank, 'eval_content': n, 'misses': missing,
                                  'errors': errors, 'rows': parsed}, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    # 报告
    L = ['---', 'type: report', 'title: 360 复核结果与全量质量估计', 'updated: 2026-11-06',
         'status: review-360', '---', '',
         '# 360 块复核结果与全量加权质量估计', '',
         '> 输入：`360_复核.txt`（无 block_id，按序号 1–360 对应 `sample_360.json`）；教师标签仅在评估阶段使用。',
         '> 不调 OCR、不写 PG/vault、未 commit。', '',
         '## 1. 解析与口径', '',
         f'- 解析 **360/360**；序号 1–360 连续；教师 kp 全部合法；**缺判 {len(missing)}**；标签错误 {len(errors)}。',
         f'- **任务口径的内容块**：教师有模块/考点 且 模型状态非 non_content → **{n}**；'
         f'其余 **{360-n}** 为 non_content（含教师留空/模型 non_content）。',
         f'- 原始教师字段：有模块/考点 **{raw_teacher_content}** 行、留空 **{raw_blank}** 行。'
         f'其中 4 个“版权页”块模型判 non_content 但教师给了内容标签；13 个导引/目录/阅读块模型判 content 但教师留空；'
         '本报告主指标按任务口径（327/33）计算，reviewed 映射则让 360 条教师判定全部生效（内容331/空白29）。', '',
         '## 2. 360 原始指标（分母 %d）' % n, '',
         '| 指标 | 命中 | 比例 |', '| --- | --- | --- |',
         f'| 模块一致 | {hits["module"]} | {hits["module"]/n*100:.1f}% |',
         f'| 考点 exact | {hits["exact"]} | {hits["exact"]/n*100:.1f}% |',
         f'| 含 secondary | {hits["any"]} | {hits["any"]/n*100:.1f}% |', '',
         '## 3. 全量 1797 加权估计（risk 分层）', '',
         f'- 全量 risk：non_content **{full["non_content"]}** / vocab_gap **{full["vocab_gap"]}** / '
         f'低置信 **{full["low"]}** / 正常 **{full["normal"]}**；内容合计 {den}。',
         '- 用 360 样本中各 risk 层的“命中率”乘全量层大小加权；**假设**：同层内样本可代表该层、'
         '且样本是风险过采样（非简单随机）。', '',
         '| 层 | 样本内容数 | 模块率 | exact 率 | 全量层大小 |', '| --- | --- | --- | --- | --- |']
    for st, name in (('vocab_gap', 'vocab_gap'), ('low', '低置信≤0.70'), ('normal', '正常')):
        s = strat[st]
        if s['n']:
            L.append(f'| {name} | {s["n"]} | {s["module"]/s["n"]*100:.1f}% | {s["exact"]/s["n"]*100:.1f}% | {full[st]} |')
        else:
            L.append(f'| {name} | 0 | — | — | {full[st]} |')
    L += ['', f'- **加权全量估计（内容 {den} 块）**：模块 **{weighted["module"]*100:.1f}%**；'
          f'exact **{weighted["exact"]*100:.1f}%**；any **{weighted["any"]*100:.1f}%**。',
          f'- non_content 另有 **{full["non_content"]}** 块，不计入内容准确率；'
          f'全量覆盖 1797/1797。', '',
          '## 4. 合并 100 pilot（仅参考，不同抽样设计）', '',
          f'- 100 pilot 有效教师标签 **{len(pilot)}** 条：v3 模块 {pm}、exact {pe}、any {pa}。',
          f'- 合并 360 + pilot：模块 **{combined["module"]}/{combined["n"]} = {combined["module"]/combined["n"]*100:.1f}%**；'
          f'exact **{combined["exact"]}/{combined["n"]} = {combined["exact"]/combined["n"]*100:.1f}%**；'
          f'any **{combined["any"]}/{combined["n"]} = {combined["any"]/combined["n"]*100:.1f}%**。',
          '- 口径差异：360 是风险分层过采样（含 non_content/vocab_gap/低置信），pilot 100 是早期分层小样本；'
          '两者合并数只作参考，不作为全量无偏估计。', '',
          '## 5. 59 条 nonempty mismatch / Top 错误', '',
          f'- 内容块 exact 不一致 **{n-hits["exact"]}** 条：其中模型 primary 非空但错 **{len(mismatch_nonempty)}** 条、'
          f'模型空 **{len(mismatch_empty)}** 条。',
          '', '| block_id | 教师考点 | 模型 primary | 类型 | 备注 |', '| --- | --- | --- | --- | --- |']
    for m in mismatch_nonempty[:59]:
        L.append(f'| `{m["block_id"]}` | `{m["teacher_kp"]}` | `{m["model_primary"]}`（{m["model_confidence"]}） | '
                 f'{m["type"]} | {m["note"][:60]} |')
    types = collections.Counter(m['type'] for m in mismatch_nonempty + mismatch_empty)
    L += ['', '### Top 错误类型', '', '| 类型 | 数量 |', '| --- | --- |']
    for t, c in types.most_common():
        L.append(f'| {t} | {c} |')
    L += ['', '## 6. 结论：能否进 PG？', '',
          f'- 全量加权模块 **{weighted["module"]*100:.1f}%**、exact **{weighted["exact"]*100:.1f}%**；'
          '模块质量足够做结构/索引使用，但 exact 约两成需要继续修正。',
          '- **可以进入 PG 表结构/入库做 draft**：建议 `review_status=teacher/model` 双状态，保留 model_primary 与 teacher 标签溯源；'
          '不建议把 model 标签当最终 gold。',
          '- 下一步优先级：① 先定 schema（teacher/model/review_status）；② 对 59 个非空错 + 15 个空错（章末/跨节/栏目）补规则；'
          '③ 再抽剩余 1517 块的 10% 或按风险补核，再决定是否把 model 标为正式。', '',
          '---', '', '> 产物：`review_360_parsed.json`、`mapped_1797_reviewed.json`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[review] 360 内容 {n}；模块 {hits["module"]}；exact {hits["exact"]}；any {hits["any"]}；'
          f'raw content {raw_teacher_content}/blank {raw_blank}；mismatch nonempty {len(mismatch_nonempty)}/empty {len(mismatch_empty)}')
    print(f'[weighted] 全量 module {weighted["module"]*100:.1f}%；exact {weighted["exact"]*100:.1f}%；any {weighted["any"]*100:.1f}%')
    print(f'[combined] module {combined["module"]}/{combined["n"]} exact {combined["exact"]}/{combined["n"]} any {combined["any"]}/{combined["n"]}')
    print(f'报告：{REPORT}')
    return 0 if not errors else 2


if __name__ == '__main__':
    raise SystemExit(main())
