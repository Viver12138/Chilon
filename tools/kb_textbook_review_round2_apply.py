#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析 v4 20% 复核回填 txt（4 列：序号/教师模块/教师考点/备注），应用 teacher 到 reviewed。

- txt 无 block_id，按序号对应**复核表 xlsx 的排序**（册 → 页码 → part → ordinal）；
- 教师留空（—）= 非内容块，映射为 non_content；
- 校验：288 行连续、模块/考点合法且同模块、重复检查；
- 产出：parsed json、round2 reviewed json（teacher 648 / model 1149）、复核报告。
不连 DB、不写 vault、不调 OCR。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
TXT = ROOT / 'review_sheets' / 'filled' / '教材映射复核_v4.txt'
SAMPLE = OUT / 'sample_review_v4_20pct_2026-11-06.json'
REVIEWED = OUT / 'mapped_1797_reviewed_v4.json'
PARSED = OUT / 'review_round2_parsed.json'
OUT_REVIEWED = OUT / 'mapped_1797_reviewed_round2.json'
REPORT = ROOT / 'docs' / 'textbook_review_v4_20pct_2026-11-06.md'
MAPPED_V3 = OUT / 'mapped_1797.json'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
BOOK_ORDER = ['必修第一册', '必修第二册', '选择性必修第一册', '选择性必修第二册', '选择性必修第三册']


def die(msg):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(2)


def book_key(title: str) -> str:
    for suffix in sorted(BOOK_ORDER, key=len, reverse=True):
        if title.endswith(suffix):
            return suffix
    return title


def load_vocab():
    mods, kps, names = {}, {}, {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mods[m.group(2)] = re.split(r'（', m.group(1))[0].strip()
        if line.strip().startswith('|'):
            parts = [x.strip().strip('`') for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0]):
                kps[parts[0]] = parts[1]
    return mods, kps, names


def parse_txt(path):
    text = pathlib.Path(path).read_text(encoding='utf-8')
    rows = []
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) == 4 and re.fullmatch(r'\d+', parts[0]):
            rows.append({'idx': int(parts[0]), 'teacher_module': parts[1],
                         'teacher_kp': parts[2], 'note': parts[3]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='解析 v4 20% 复核回填 txt')
    ap.add_argument('--txt', default=str(TXT))
    ap.add_argument('--sample', default=str(SAMPLE))
    ap.add_argument('--reviewed', default=str(REVIEWED))
    ap.add_argument('--out-reviewed', default=str(OUT_REVIEWED))
    ap.add_argument('--out-parsed', default=str(PARSED))
    ap.add_argument('--report', default=str(REPORT))
    ap.add_argument('--apply-teacher', action='store_true', help='把 teacher 标签写进 out-reviewed')
    args = ap.parse_args(argv)

    mods, kps, _ = load_vocab()
    reviewed = json.loads(pathlib.Path(args.reviewed).read_text(encoding='utf-8'))['items']
    byid = {x['block_id']: x for x in reviewed}
    sample = json.loads(pathlib.Path(args.sample).read_text(encoding='utf-8'))
    ids = sample['block_ids']
    if len(ids) != 288:
        die(f'sample 不是 288：{len(ids)}')
    # 与复核表 xlsx 完全相同的排序
    ordered = sorted((byid[i] for i in ids),
                     key=lambda x: (BOOK_ORDER.index(book_key(x['book'])), x['page'],
                                    x.get('part') or 0, x.get('ordinal') or 0))
    rows = parse_txt(args.txt)
    if len(rows) != 288:
        die(f'txt 解析 {len(rows)} 行，应为 288')
    if [r['idx'] for r in rows] != list(range(1, 289)):
        die('序号不是 1–288 连续')

    errors, parsed = [], []
    for r, x in zip(rows, ordered):
        tm, tk = r['teacher_module'], r['teacher_kp']
        blank = tm in ('—', '-', '') and tk in ('—', '-', '')
        if not blank:
            if tm in ('—', '-', '') or tk in ('—', '-', ''):
                errors.append((r['idx'], '模块/考点只有一个留空', tm, tk))
                continue
            if tm not in mods:
                errors.append((r['idx'], '教师模块不合法', tm, tk))
                continue
            if tk not in kps:
                errors.append((r['idx'], '教师考点不合法', tm, tk))
                continue
            if tm.split('_')[1] != tk.split('_')[1]:
                errors.append((r['idx'], '模块与考点不同模块', tm, tk))
                continue
        parsed.append({**x, 'index': r['idx'], 'teacher_module': '' if blank else tm,
                       'teacher_kp': '' if blank else tk, 'note': r['note'],
                       'has_teacher': not blank})
    if errors:
        for e in errors[:10]:
            print(e)
        die(f'{len(errors)} 条标签错误')

    # 指标：教师内容块（有标签）且 v4 模型状态非 non_content
    content = [p for p in parsed if p['has_teacher'] and p['model_status'] != 'non_content']
    n = len(content)
    exact = sum(1 for p in content if p['teacher_kp'] == (p['model_primary'] or ''))
    module = sum(1 for p in content if p['model_primary'] and
                 p['model_primary'].split('_')[1] == p['teacher_module'].split('_')[1])
    any_ = sum(1 for p in content if p['teacher_kp'] in
               (([p['model_primary']] if p['model_primary'] else []) + list(p['model_secondary'] or [])))
    v3 = {x['block_id']: x for x in json.loads(MAPPED_V3.read_text(encoding='utf-8'))['items']}
    v3_exact = sum(1 for p in content if (v3.get(p['block_id'], {}).get('kp_primary') or '') == p['teacher_kp'])
    fixed = sum(1 for p in content if (v3.get(p['block_id'], {}).get('kp_primary') or '') != p['teacher_kp']
                and (p['model_primary'] or '') == p['teacher_kp'])
    harmed = sum(1 for p in content if (v3.get(p['block_id'], {}).get('kp_primary') or '') == p['teacher_kp']
                 and (p['model_primary'] or '') != p['teacher_kp'])
    print(f'[v3->v4] v3 exact {v3_exact}/{n}={v3_exact/n*100:.1f}%；v4 exact {exact}/{n}={exact/n*100:.1f}%；'
          f'fixed {fixed} / harmed {harmed}')
    blank_content = [p for p in parsed if not p['has_teacher'] and p['model_status'] != 'non_content']
    label_non = [p for p in parsed if p['has_teacher'] and p['model_status'] == 'non_content']
    print(f'[parsed] 288 行；教师有标签 {len(parsed) - sum(1 for p in parsed if not p["has_teacher"])}，'
          f'留空 {sum(1 for p in parsed if not p["has_teacher"])}；内容分母 {n}；'
          f'模块 {module}/{n}={module/n*100:.1f}% exact {exact}/{n}={exact/n*100:.1f}% any {any_}/{n}')
    print(f'[blank] 教师留空但模型为内容：{len(blank_content)}；模型 non_content 但教师给标签：{len(label_non)}')

    # 应用 teacher
    new_reviewed = []
    applied = 0
    for x in reviewed:
        p = next((q for q in parsed if q['block_id'] == x['block_id']), None)
        rec = dict(x)
        # 旧 teacher 360 行保留原版本；本轮新增 teacher 行标 round2 版本
        if rec.get('review_status') == 'teacher' and not rec.get('teacher_version'):
            rec['teacher_version'] = 'textbook-review-2026-11-06'
        if p is not None:
            rec['review_status'] = 'teacher'
            rec['teacher_version'] = 'textbook-review-v4-round2-2026-11-06'
            rec['teacher_module'] = p['teacher_module']
            rec['teacher_kp'] = p['teacher_kp']
            rec['teacher_note'] = p['note']
            rec['model_primary'] = x.get('model_primary', x.get('kp_primary', ''))
            rec['model_secondary'] = list(x.get('model_secondary') or [])
            rec['model_status'] = x.get('model_status', x.get('status'))
            if p['has_teacher']:
                rec['kp_primary'] = p['teacher_kp']
                rec['module'] = p['teacher_kp'].split('_')[1]
                rec['module_id'] = p['teacher_module']
                rec['kp_name'] = kps[p['teacher_kp']]
                rec['status'] = 'mapped'
                rec['confidence'] = 1.0
                rec['reason'] = p['note'] or '教师复核（20% 抽样第二轮）'
            else:
                rec['kp_primary'] = ''
                rec['module'] = ''
                rec['module_id'] = ''
                rec['kp_name'] = ''
                rec['kp_secondary'] = []
                rec['status'] = 'non_content'
                rec['confidence'] = 1.0
                rec['reason'] = p['note'] or '教师复核：非内容/不映射'
            applied += 1
        new_reviewed.append(rec)
    if len(new_reviewed) != 1797:
        die('reviewed 不是 1797')
    teacher = sum(1 for x in new_reviewed if x.get('review_status') == 'teacher')
    print(f'[apply] teacher {teacher} / model {len(new_reviewed) - teacher}；本轮覆盖 {applied}')
    # 与 teacher 360 不重叠
    old_teacher = {x['block_id'] for x in reviewed if x.get('review_status') == 'teacher'}
    overlap = old_teacher & {p['block_id'] for p in parsed}
    if overlap:
        die(f'本轮与已有 teacher 360 重叠 {len(overlap)} 条（不应发生）')

    # 顺序按 JSON 原有顺序写回
    pathlib.Path(args.out_parsed).write_text(json.dumps(
        {'txt': str(TXT), 'rows': parsed, 'metrics': {'content': n, 'module': module, 'exact': exact,
                                                      'any': any_, 'blank_content': len(blank_content),
                                                      'label_non_content': len(label_non)}},
        ensure_ascii=False, indent=1), encoding='utf-8')
    if args.apply_teacher:
        pathlib.Path(args.out_reviewed).write_text(json.dumps(
            {'count': len(new_reviewed), 'teacher_count': teacher, 'items': new_reviewed},
            ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[write] {args.out_reviewed}（teacher {teacher} / model {len(new_reviewed) - teacher}）')

    # 报告
    by_risk = collections.Counter()
    for p in parsed:
        by_risk['blank_non_content' if not p['has_teacher'] and p['model_status'] == 'non_content' else
                'blank_on_content' if not p['has_teacher'] else
                'teacher_on_non_content' if p['model_status'] == 'non_content' else 'teacher_on_content'] += 1
    # 低置信/正常层准确率
    def risk_of(p):
        if not p['has_teacher']:
            return 'blank'
        if (p.get('confidence') or 0) <= 0.70:
            return 'low_conf'
        return 'normal'
    layer = collections.defaultdict(lambda: [0, 0])
    for p in parsed:
        if not p['has_teacher'] or p['model_status'] == 'non_content':
            continue
        k = risk_of(p)
        layer[k][0] += 1
        layer[k][1] += p['teacher_kp'] == (p['model_primary'] or '')
    L = ['---', 'type: report', 'title: 教材 v4 20% 复核结果（288 块，2026-11-06）', 'updated: 2026-11-06',
         'status: review-round2', '---', '',
         '# 教材 v4 20% 复核结果（288 块）', '',
         '> 输入：`review_sheets/filled/教材映射复核_v4.txt`（4 列，无 block_id，按序号对应复核表 xlsx 排序）；',
         '> 教师标签只用于评估与 reviewed 更新；不调 OCR、未写 vault（链接重投影另做）。', '',
         '## 1. 解析与口径', '',
         f'- 解析 **288/288**，序号 1–288 连续；模块/考点合法、同模块校验通过；',
         f'- 教师有标签 **{288 - by_risk["blank_on_content"] - by_risk["blank_non_content"]}**，'
         f'留空 **{by_risk["blank_on_content"] + by_risk["blank_non_content"]}**；',
         f'- 内容分母（教师有标签且 v4 模型非 non_content）= **{n}**。', '',
         '## 2. 模型准确率（v4 在 288 块上的样本指标）', '',
         '| 指标 | 命中 | 比例 |', '| --- | ---: | ---: |',
         f'| 模块一致 | {module} | {module/n*100:.1f}% |',
         f'| 考点 exact | {exact} | {exact/n*100:.1f}% |',
         f'| 含 secondary | {any_} | {any_/n*100:.1f}% |',
         f'| v3 对照 exact | {v3_exact} | {v3_exact/n*100:.1f}% |', '',
         f'- v3→v4 同分母对照：修好 **{fixed}**、改坏 **{harmed}**（以教师标签为准）。', '',
         '### 分层', '', '| 层 | 分母 | exact | 比例 |', '| --- | ---: | ---: | ---: |']
    for k in ('low_conf', 'normal'):
        d, e = layer[k]
        L.append(f'| {k} | {d} | {e} | {e/d*100 if d else 0:.1f}% |')
    L += ['', '## 3. 留空与 cross 情况', '',
          f'- 教师留空但模型判内容：**{len(blank_content)}** 条；',
          f'- 模型判 non_content 但教师给标签：**{len(label_non)}** 条；',
          '- 本轮按教师判定处理：留空 → non_content；有标签 → mapped。', '',
          '## 4. reviewed 更新', '',
          f'- `{pathlib.Path(args.out_reviewed).name}`：teacher **{teacher}** / model **{len(new_reviewed) - teacher}**；',
          f'- 本轮新增 teacher **{applied}** 条；与已有 teacher 360 **零重叠**。', '',
          '---', '',
          '> 明细：`review_round2_parsed.json`。', '']
    pathlib.Path(args.report).write_text('\n'.join(L), encoding='utf-8')
    print(f'报告：{args.report}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
