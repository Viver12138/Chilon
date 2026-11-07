#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""解析第三批组合复核回填（复核_v5.txt，5 列含 block_id），应用 teacher 到 reviewed。

- 语义：教师模块+考点都有 → mapped；只有模块、无考点 → vocab_gap（词表缺口，保留模块）；
        模块/考点都空 → non_content；
- 校验：block_id 集合与组合 sample json 完全一致、标签合法且同模块、序号 1–N 连续；
- 产出：parsed json、round3 reviewed、复核报告。不连 DB、不写 vault。
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
TXT = ROOT / 'review_sheets' / 'filled' / '复核_v5.txt'
SAMPLE = OUT / 'sample_review_v5_20pct_pilot100_2026-11-07.json'
REVIEWED = OUT / 'mapped_1797_reviewed_v5.json'
PARSED = OUT / 'review_round3_parsed.json'
OUT_REVIEWED = OUT / 'mapped_1797_reviewed_round3.json'
REPORT = ROOT / 'docs' / 'textbook_review_v5_round3_2026-11-07.md'
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))
TEACHER_VERSION = 'textbook-review-v5-round3-2026-11-07'


def die(msg):
    print(f'[失败] {msg}', file=sys.stderr)
    sys.exit(2)


def load_vocab():
    mods, kps = {}, {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            mods[m.group(2)] = re.split(r'（', m.group(1))[0].strip()
        if line.strip().startswith('|'):
            p = [x.strip().strip('`') for x in line.strip().strip('|').split('|')]
            if len(p) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', p[0]):
                kps[p[0]] = p[1]
    return mods, kps


def parse_txt(path):
    rows = []
    for line in pathlib.Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        p = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(p) == 5 and re.fullmatch(r'\d+', p[0]):
            rows.append({'idx': int(p[0]), 'block_id': p[1], 'tm': p[2], 'tk': p[3], 'note': p[4]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='解析第三批组合复核回填')
    ap.add_argument('--txt', default=str(TXT))
    ap.add_argument('--sample', default=str(SAMPLE))
    ap.add_argument('--reviewed', default=str(REVIEWED))
    ap.add_argument('--out-reviewed', default=str(OUT_REVIEWED))
    ap.add_argument('--out-parsed', default=str(PARSED))
    ap.add_argument('--report', default=str(REPORT))
    ap.add_argument('--apply-teacher', action='store_true')
    ap.add_argument('--teacher-version', default=TEACHER_VERSION)
    ap.add_argument('--batch-label', default='第三批组合复核结果（310 块：20% + pilot100）')
    ap.add_argument('--engine-label', default='v5')
    ap.add_argument('--source-label', default='20%抽样')
    ap.add_argument('--census', action='store_true', help='全量终检（非抽样）')
    args = ap.parse_args(argv)

    mods, kps = load_vocab()
    reviewed = json.loads(pathlib.Path(args.reviewed).read_text(encoding='utf-8'))['items']
    byid = {x['block_id']: x for x in reviewed}
    meta = json.loads(pathlib.Path(args.sample).read_text(encoding='utf-8'))
    sample_ids = set(meta['block_ids'])
    by_chunk = {x['chunk_id']: x['block_id'] for x in
                json.loads((OUT / 'mapped_1797_v5.json').read_text(encoding='utf-8'))['items']}
    pilot_ids = {by_chunk[b['chunk_id']] for b in
                 json.loads((OUT / 'sample_100.json').read_text(encoding='utf-8'))['blocks']
                 if b['chunk_id'] in by_chunk}
    rows = parse_txt(args.txt)
    if len(rows) != len(sample_ids):
        die(f'回填 {len(rows)} 行，样本 {len(sample_ids)}')
    if [r['idx'] for r in rows] != list(range(1, len(rows) + 1)):
        die('序号不连续')
    if {r['block_id'] for r in rows} != sample_ids:
        die(f'block_id 与样本不一致：缺 {len(sample_ids - {r["block_id"] for r in rows})}，'
            f'多 {len({r["block_id"] for r in rows} - sample_ids)}')

    errors, parsed = [], []
    for r in rows:
        tm, tk = r['tm'], r['tk']
        blank_mod = tm in ('', '—', '-')
        blank_kp = tk in ('', '—', '-')
        if blank_mod and not blank_kp:
            errors.append((r['idx'], '有考点但模块留空', tm, tk))
        if not blank_mod and tm not in mods:
            errors.append((r['idx'], '模块不合法', tm, tk))
        if not blank_kp:
            if tk not in kps:
                errors.append((r['idx'], '考点不合法', tm, tk))
            elif tm.split('_')[1] != tk.split('_')[1]:
                errors.append((r['idx'], '模块与考点不同模块', tm, tk))
        kind = 'blank' if (blank_mod and blank_kp) else ('module_only' if blank_kp else 'full')
        parsed.append({**byid[r['block_id']], 'index': r['idx'],
                       'teacher_module': '' if blank_mod else tm,
                       'teacher_kp': '' if blank_kp else tk,
                       'teacher_note': r['note'], 'kind': kind,
                       'source': 'pilot100' if r['block_id'] in pilot_ids else args.source_label})
    if errors:
        for e in errors[:10]:
            print(e)
        die(f'{len(errors)} 条标签错误')

    full = [p for p in parsed if p['kind'] == 'full']
    modonly = [p for p in parsed if p['kind'] == 'module_only']
    blank = [p for p in parsed if p['kind'] == 'blank']
    fm = sum(1 for p in full if p['teacher_kp'] == (p['model_primary'] or ''))
    fmod = sum(1 for p in full if p['model_primary'] and
               p['model_primary'].split('_')[1] == p['teacher_module'].split('_')[1])
    content_all = full + modonly
    em_all = sum(1 for p in content_all if (p['model_primary'] or '') == p['teacher_kp'])
    mod_all = sum(1 for p in content_all if p['model_primary'] and
                  p['model_primary'].split('_')[1] == p['teacher_module'].split('_')[1])
    print(f'[parsed] rows {len(parsed)}；full {len(full)}（module {fmod} exact {fm} = {fm/len(full)*100:.1f}%）、'
          f'module_only {len(modonly)}、blank {len(blank)}；'
          f'blank on model content {sum(1 for p in blank if p["status"] != "non_content")}')

    # 应用 teacher
    new_reviewed, applied = [], 0
    for x in reviewed:
        rec = dict(x)
        if rec.get('review_status') == 'teacher' and not rec.get('teacher_version'):
            rec['teacher_version'] = 'textbook-review-2026-11-06'
        p = next((q for q in parsed if q['block_id'] == x['block_id']), None)
        if p is not None:
            rec['review_status'] = 'teacher'
            rec['teacher_version'] = args.teacher_version
            rec['teacher_module'] = p['teacher_module']
            rec['teacher_kp'] = p['teacher_kp']
            rec['teacher_note'] = p['teacher_note']
            rec['model_primary'] = x.get('model_primary', x.get('kp_primary', ''))
            rec['model_secondary'] = list(x.get('model_secondary') or [])
            rec['model_status'] = x.get('model_status', x.get('status'))
            if p['kind'] == 'full':
                rec.update({'kp_primary': p['teacher_kp'], 'module': p['teacher_kp'].split('_')[1],
                            'module_id': p['teacher_module'], 'kp_name': kps[p['teacher_kp']],
                            'kp_secondary': [], 'status': 'mapped', 'confidence': 1.0,
                            'reason': p['teacher_note'] or '教师复核'})
            elif p['kind'] == 'module_only':
                rec.update({'kp_primary': '', 'module': p['teacher_module'].split('_')[1],
                            'module_id': p['teacher_module'], 'kp_name': '', 'kp_secondary': [],
                            'status': 'vocab_gap', 'confidence': 1.0,
                            'reason': p['teacher_note'] or '教师复核：有模块但无合适主考点'})
            else:
                rec.update({'kp_primary': '', 'module': '', 'module_id': '', 'kp_name': '',
                            'kp_secondary': [], 'status': 'non_content', 'confidence': 1.0,
                            'reason': p['teacher_note'] or '教师复核：非内容/不映射'})
            applied += 1
        new_reviewed.append(rec)
    if len(new_reviewed) != 1797:
        die('reviewed 不是 1797')
    teacher = sum(1 for x in new_reviewed if x.get('review_status') == 'teacher')
    status = collections.Counter(x['status'] for x in new_reviewed)
    print(f'[apply] teacher {teacher} / model {len(new_reviewed) - teacher}；status {dict(status)}；覆盖 {applied}')
    old_teacher = {x['block_id'] for x in reviewed if x.get('review_status') == 'teacher'}
    if old_teacher & {p['block_id'] for p in parsed}:
        die('本轮与已有 teacher 648 重叠')

    pathlib.Path(args.out_parsed).write_text(json.dumps({
        'txt': str(args.txt), 'rows': [{k: v for k, v in p.items() if k not in ('detail',)} for p in parsed],
        'summary': {'full': len(full), 'module_only': len(modonly), 'blank': len(blank),
                    'full_exact': fm, 'full_module': fmod,
                    'blank_on_content': sum(1 for p in blank if p['status'] != 'non_content'),
                    'by_source': dict(collections.Counter(p['source'] for p in parsed))},
    }, ensure_ascii=False, indent=1), encoding='utf-8')
    if args.apply_teacher:
        pathlib.Path(args.out_reviewed).write_text(json.dumps(
            {'count': len(new_reviewed), 'teacher_count': teacher, 'items': new_reviewed},
            ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[write] {args.out_reviewed}（teacher {teacher} / model {len(new_reviewed) - teacher}）')

    # 报告
    mism = [p for p in full if (p['model_primary'] or '') != p['teacher_kp']]
    n_sample = len(sample_ids)
    has_pilot = any(p['source'] == 'pilot100' for p in parsed)
    pilot_note = ('pilot 100 的历史欠账已补。' if has_pilot
                  else '本轮为剩余模型抽样，无 pilot 回采。')
    L = ['---', 'type: report', f'title: 教材{args.batch_label}',
         'updated: 2026-11-07', 'status: review-batch', '---', '',
         f'# 教材{args.batch_label}', '',
         f'> 输入：`{pathlib.Path(args.txt).name}`（5 列含 block_id）；{args.engine_label} 映射为候选；',
         '> 教师标签 → reviewed/PG/Obsidian 链接；不调 OCR。', '',
         '## 1. 解析与口径', '',
         f'- 解析 **{len(parsed)}/{n_sample}**，block_id 与样本一致；模块/考点合法且同模块；',
         f'- 教师完整标签 **{len(full)}**、只有模块无考点 **{len(modonly)}**、留空 **{len(blank)}**；',
         f'- 留空 → non_content（其中模型原判内容 {sum(1 for p in blank if p["status"] != "non_content")} 条）；',
         '- 只有模块无考点 → vocab_gap（保留模块，表示“词表缺合适考点/不宜硬塞”）。', '',
         f'## 2. {args.engine_label} 在本批上的准确率', '',
         '| 口径 | 分母 | 模块 | exact |', '| --- | ---: | ---: | ---: |',
         f'| 完整标签（module+exact） | {len(full)} | {fmod} = {fmod/len(full)*100:.1f}% | '
         f'{fm} = {fm/len(full)*100:.1f}% |',
         f'| 含 module_only（exact 记 0） | {len(content_all)} | {mod_all} = '
         f'{mod_all/len(content_all)*100:.1f}% | {em_all} = {em_all/len(content_all)*100:.1f}% |', '',
         f'### 不一致清单（{args.engine_label} 错、教师对，{len(mism)} 条，供下一版规则）', '',
         '| block_id | 教师 | ' + args.engine_label + ' | 来源 | 备注 |', '| --- | --- | --- | --- | --- |']
    for p in mism:
        L.append(f'| `{p["block_id"]}` | `{p["teacher_kp"]}` | `{p["model_primary"] or "（空）"}` | '
                 f'{p["source"]} | {p["teacher_note"][:40]} |')
    L += ['', '## 3. reviewed 更新', '',
          f'- `{pathlib.Path(args.out_reviewed).name}`：teacher **{teacher}** / model **{len(new_reviewed) - teacher}**；',
          f'- 本轮新增 teacher **{applied}** 条（上批 {teacher - applied} 不动）；status {dict(status)}。', '',
          '## 4. 边界', '',
          ('- 本轮为**全量终检**（非抽样）；准确率覆盖剩余池全部块，但仍不是 1797 的随机样本；'
           if args.census else '- 抽样/回采不是全量；准确率仍是样本值；'),
          f'- module_only {len(modonly)} 条按“有模块、无合适主考点”记 vocab_gap，不强行塞考点；',
          f'- {len(mism)} 条不一致留待下一版规则收敛；{pilot_note}', '',
          '---', '', f'> 明细：`{pathlib.Path(args.out_parsed).name}`。', '']
    pathlib.Path(args.report).write_text('\n'.join(L), encoding='utf-8')
    print(f'报告：{args.report}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
