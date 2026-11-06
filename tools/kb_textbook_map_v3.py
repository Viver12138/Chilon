#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材映射 v3：固定 chapter/section，用 section→kp 词典 + 正文关键词细化。

约束：映射阶段不读取教师标签；教师标签只在 v3 输出后评估（分母 88）。
不调 OCR、不写 PG/vault、不 commit。
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
STRUCT = OUT / 'structure_5books.json'
BLOCKS = OUT / 'blocks_1797_with_structure.json'
SAMPLE = OUT / 'sample_100.json'
V2 = OUT / 'mapped_100_v2.json'
V1 = OUT / 'mapped_100.json'
OUTFILE = OUT / 'mapped_100_v3.json'
BATCH = OUT / 'mapped_100_v3_batch.txt'
DICT = OUT / 'section_kp_dictionary.json'
REPORT = OUT / 'pilot_v3_report.md'
TEACHER = pathlib.Path(os.environ['CHILON_TEACHER_LABELS']) if os.environ.get('CHILON_TEACHER_LABELS') else None

# 章级模块约束（人工知识，非教师标签）
CHAPTER_MODULES = {
    ('必修第一册', 1): ['01'], ('必修第一册', 2): ['02', '12'], ('必修第一册', 3): ['02'],
    ('必修第一册', 4): ['02'], ('必修第一册', 5): ['04'],
    ('必修第二册', 6): ['05'], ('必修第二册', 7): ['06'], ('必修第二册', 8): ['08'],
    ('必修第二册', 9): ['10'], ('必修第二册', 10): ['10'],
    ('选择性必修第一册', 1): ['08'], ('选择性必修第一册', 2): ['09'], ('选择性必修第一册', 3): ['09'],
    ('选择性必修第二册', 4): ['07'], ('选择性必修第二册', 5): ['03'],
    ('选择性必修第三册', 6): ['11'], ('选择性必修第三册', 7): ['10'], ('选择性必修第三册', 8): ['10'],
}
# 节标题过泛/OCR 不完整时的人工候选（仅按课标/节名，不看教师标签）
OVERRIDES = {
    ('必修第一册', '3.2'): ['kp_02_04_monotonic', 'kp_02_05_parity', 'kp_02_06_period'],
    ('必修第一册', '3.2.2'): ['kp_02_05_parity'],
    ('必修第一册', '5.5'): ['kp_04_03_sumdiff', 'kp_04_04_double', 'kp_04_02_identity'],
    ('必修第一册', '5.5.2'): ['kp_04_03_sumdiff', 'kp_04_04_double', 'kp_04_02_identity'],
    ('必修第一册', '5.6'): ['kp_04_05_graph', 'kp_04_06_transform', 'kp_04_07_range'],
    ('必修第二册', '6.3'): ['kp_05_06_decompose', 'kp_05_02_coordinate'],
    ('必修第二册', '6.4'): ['kp_05_08_apply', 'kp_05_03_dot', 'kp_05_04_perpendicular'],
    ('必修第二册', '8.4'): ['kp_08_03_position'],
    ('必修第二册', '8.5'): ['kp_08_04_parallel'],
    ('必修第二册', '8.6'): ['kp_08_05_perpendicular'],
    ('必修第二册', '8.6.2'): ['kp_08_05_perpendicular'],
    ('必修第二册', '9.2'): ['kp_10_03_central', 'kp_10_02_histogram'],
    ('必修第二册', '9.3'): ['kp_10_10_regression', 'kp_10_11_chisquare'],
    ('必修第二册', '10.1'): ['kp_10_13_event', 'kp_10_04_classical'],
    ('必修第二册', '10.2'): ['kp_10_06_event'],
    ('必修第二册', '10.3'): ['kp_10_04_classical'],
    ('选择性必修第一册', '1.4'): ['kp_08_07_vector'],
    ('选择性必修第一册', '2.5'): ['kp_09_03_line_circle'],
    ('选择性必修第一册', '2.5.2'): ['kp_09_03_line_circle'],
    ('选择性必修第一册', '3.1'): ['kp_09_05_ellipse'],
    ('选择性必修第一册', '3.2'): ['kp_09_06_hyperbola'],
    ('选择性必修第一册', '3.3'): ['kp_09_07_parabola'],
    ('选择性必修第一册', '3.3.2'): ['kp_09_07_parabola'],
    ('选择性必修第三册', '7.1'): ['kp_10_07_conditional'],
    ('选择性必修第三册', '7.1.2'): ['kp_10_07_conditional'],
    ('选择性必修第三册', '7.2'): ['kp_10_08_distribution'],
    ('选择性必修第三册', '7.3'): ['kp_10_08_distribution'],
    ('选择性必修第三册', '7.4'): ['kp_10_09_binomial'],
    ('选择性必修第三册', '7.5'): ['kp_10_12_normal'],
    ('选择性必修第三册', '8.1'): ['kp_10_10_regression'],
    ('选择性必修第三册', '8.2'): ['kp_10_10_regression'],
    ('选择性必修第三册', '8.3'): ['kp_10_11_chisquare'],
    ('选择性必修第二册', '4.4'): ['kp_07_08_induction'],
    ('选择性必修第二册', '5.1'): ['kp_03_08_concept'],
    ('选择性必修第二册', '5.2'): ['kp_03_01_compute'],
    ('选择性必修第二册', '5.2.2'): ['kp_03_01_compute'],
    ('选择性必修第二册', '5.3'): ['kp_03_03_monotonic', 'kp_03_04_extremum', 'kp_03_05_param_hold',
                                      'kp_03_06_zeros', 'kp_03_02_tangent', 'kp_03_07_proof'],
}


def load():
    spec = importlib.util.spec_from_file_location('tb1', ROOT / 'tools' / 'kb_textbook_map_pilot.py')
    tb1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(tb1)
    spec = importlib.util.spec_from_file_location('mockann', ROOT / 'tools' / 'kb_mock_annotate_full.py')
    mockann = importlib.util.module_from_spec(spec); spec.loader.exec_module(mockann)
    return tb1, mockann


def book_key(title):
    for suffix in sorted(['选择性必修第三册', '选择性必修第二册', '选择性必修第一册',
                          '必修第一册', '必修第二册'], key=len, reverse=True):
        if title.endswith(suffix):
            return suffix
    return title


def build_dictionary(structure, vocab, mockann):
    """section 标题→候选 kp（章内词表打分 + 人工 overrides）；不读教师标签。"""
    dictionary = {}
    for sec in structure['sections']:
        bk = book_key(sec['book'])
        key = f'{bk}|{sec["section_num"]}'
        if (bk, sec['section_num']) in OVERRIDES:
            cand = OVERRIDES[(bk, sec['section_num'])]
        else:
            allowed = CHAPTER_MODULES.get((bk, sec['chapter_num']))
            sc = {}
            for text in (sec['section'], sec.get('chapter', '')):
                ss, _m = mockann.score_question(text, [], vocab)
                for k, v in ss.items():
                    if allowed and k.split('_')[1] not in allowed:
                        continue
                    sc[k] = sc.get(k, 0) + v
            cand = [k for k, _v in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:3] if _v >= 1]
        dictionary[key] = {'section': sec['section'], 'candidates': cand}
    return dictionary


def map_block(block, vocab, mockann, tb1, dictionary):
    text = block['text']
    non, reason = tb1.is_non_content(text, block.get('page'), block.get('part'))
    btype = tb1.block_type(text, reason if non else '')
    rec = {**block, 'block_type': btype, 'non_content': non, 'non_content_reason': reason,
           'kp_primary': '', 'module': '', 'kp_name': '', 'kp_secondary': [], 'confidence': 0.0,
           'reason': '', 'status': ''}
    if non:
        rec.update({'status': 'non_content', 'confidence': 0.0,
                    'reason': f'教材非内容块（{reason}），不映射知识点。'})
        return rec
    bk = book_key(block['book'])
    allowed = CHAPTER_MODULES.get((bk, block.get('chapter_num')))
    scores, matched = mockann.score_question(text, [], vocab)
    if allowed:
        scores = {k: v for k, v in scores.items() if k.split('_')[1] in allowed}
        matched = {k: v for k, v in matched.items() if k.split('_')[1] in allowed}
    sec_key = f'{bk}|{block.get("section_num", "")}'
    sec_entry = dictionary.get(sec_key, {})
    for k in sec_entry.get('candidates', []):
        scores[k] = scores.get(k, 0) + 4.0
        matched.setdefault(k, []).append('section:' + block.get('section', '')[:20])
    sec_scores, _sm = mockann.score_question(block.get('section', ''), [], vocab)
    for k, v in sec_scores.items():
        if allowed and k.split('_')[1] not in allowed:
            continue
        scores[k] = scores.get(k, 0) + v * 2.0
    ranked = sorted(((k, v) for k, v in scores.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 2.0:
        rec.update({'status': 'vocab_gap', 'confidence': 0.35,
                    'reason': '章节约束 + section 词典 + 正文均无足够证据，按 vocab_gap 留空。'})
        return rec
    top, sc = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    margin = sc - second
    if sc >= 8 and margin >= 2:
        conf = 0.92
    elif sc >= 5 and margin >= 1:
        conf = 0.85
    elif sc >= 3:
        conf = 0.72
    else:
        conf = 0.62
    if margin < 0.8:
        conf -= 0.08
    conf = round(max(0.4, min(0.95, conf)), 2)
    # secondary：只保留跨模块、且有正文/section 证据的候选；同模块更细的 kp 不加入
    secondary = []
    for k, v in ranked[1:]:
        if v < 3:
            continue
        if k.split('_')[1] == top.split('_')[1]:
            continue
        secondary.append(k)
        if len(secondary) == 2:
            break
    words = []
    for w in matched.get(top, []):
        if w not in words:
            words.append(w)
    kw = '、'.join(words[:5]) or '章节内容'
    rec.update({'kp_primary': top, 'module': top.split('_')[1], 'kp_name': vocab[top]['name'],
                'kp_secondary': secondary, 'confidence': conf,
                'reason': f'章节「{block.get("chapter","")}」/「{block.get("section","")}」+ 正文「{kw}」，'
                          f'主考{vocab[top]["name"]}；'
                          f'{"跨模块兼及" + "、".join(vocab[x]["name"] for x in secondary) if secondary else "未发现充分跨模块证据。"}',
                'status': 'mapped'})
    return rec


def parse_teacher():
    rows = []
    if TEACHER is None:
        print('[warn] 未提供教师标签（CHILON_TEACHER_LABELS），跳过评估', file=__import__('sys').stderr)
        return rows
    for line in TEACHER.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) == 7 and re.fullmatch(r'\d+', parts[0]):
            rows.append({'block_id': parts[1], 'teacher_module': parts[3], 'teacher_kp': parts[4],
                         'conclusion': parts[5], 'note': parts[6]})
    return [r for r in rows if r['teacher_module'] not in ('—', '') and r['teacher_kp'] not in ('—', '')]


def main():
    tb1, mockann = load()
    vocab = mockann.load_vocab()
    structure = json.loads(STRUCT.read_text(encoding='utf-8'))
    blocks = json.loads(BLOCKS.read_text(encoding='utf-8'))['blocks']
    v1 = {x['block_id']: x for x in json.loads(V1.read_text(encoding='utf-8'))['items']}
    v2 = {x['block_id']: x for x in json.loads(V2.read_text(encoding='utf-8'))['items']}
    dictionary = build_dictionary(structure, vocab, mockann)
    DICT.write_text(json.dumps(dictionary, ensure_ascii=False, indent=1), encoding='utf-8')
    by_chunk = {b['chunk_id']: b for b in blocks}
    v3_items = []
    for bid, old in v1.items():
        base = dict(by_chunk[old['chunk_id']])
        base['v2_primary'] = v2.get(bid, {}).get('kp_primary', '')
        rec = map_block(base, vocab, mockann, tb1, dictionary)
        rec['block_id'] = bid
        rec['v1_primary'] = old['kp_primary']
        rec['v1_secondary'] = old['kp_secondary']
        rec['v2_primary'] = v2.get(bid, {}).get('kp_primary', '')
        rec['v2_secondary'] = v2.get(bid, {}).get('kp_secondary', [])
        rec['v2_module'] = v2.get(bid, {}).get('module', '')
        v3_items.append(rec)
    OUTFILE.write_text(json.dumps({'count': len(v3_items), 'rules': 'chapter-module + section->kp dict + body keywords',
                                   'items': v3_items}, ensure_ascii=False, indent=1), encoding='utf-8')
    BATCH.write_text('\n'.join(
        f"{i:03d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['chapter']}|{x['section']}|"
        f"{x['status']}|{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}"
        for i, x in enumerate(v3_items, 1)) + '\n', encoding='utf-8')
    # evaluation only now
    teacher = parse_teacher()
    if not teacher:
        L = ['---', 'type: report', 'title: 教材映射 v3（无教师标签，仅映射）',
             'updated: 2026-11-06', 'status: pilot-v3-no-label', '---', '',
             '# 教材映射 v3 · section→kp 细化（未提供教师标签，跳过评估）', '',
             '> 映射阶段不读取教师标签；未调 OCR、未写 PG/vault、未 commit。', '',
             '1. chapter_num → 允许模块；2. section 标题 → kp 候选词典；3. 正文关键词加权；',
             '4. secondary 仅保留跨模块且证据 ≥3；5. non_content / vocab_gap 规则不变。', '',
             f'- section 词典条目：**{len(dictionary)}**；有候选：**{sum(1 for v in dictionary.values() if v["candidates"])}**',
             f'- v3 映射块数：**{len(v3_items)}**', '',
             '> 教师标签通过环境变量 CHILON_TEACHER_LABELS 提供（路径），本工具不内置个人路径。', '']
        REPORT.write_text('\n'.join(L), encoding='utf-8')
        print(f'[v3] {len(v3_items)} 块；词典 {len(dictionary)}；未提供教师标签，跳过评估')
        print(f'报告：{REPORT}')
        return 0
    n = len(teacher)
    met = {'v1': [0, 0, 0], 'v2': [0, 0, 0], 'v3': [0, 0, 0]}
    fixed, still, newwrong = [], [], []
    for t in teacher:
        bid, tm, tk = t['block_id'], t['teacher_module'].split('_')[1], t['teacher_kp']
        xs = {'v1': v1.get(bid), 'v2': v2.get(bid), 'v3': next((x for x in v3_items if x['block_id'] == bid), None)}
        if not all(xs.values()):
            continue
        for label, x in xs.items():
            p = x['kp_primary']
            met[label][0] += bool(p) and p.split('_')[1] == tm
            met[label][1] += p == tk
            met[label][2] += tk in (([p] if p else []) + list(x['kp_secondary']))
        e1 = xs['v1']['kp_primary'] == tk
        e2 = xs['v2']['kp_primary'] == tk
        e3 = xs['v3']['kp_primary'] == tk
        if not e2 and e3:
            fixed.append((t, xs['v2'], xs['v3']))
        elif e2 and not e3:
            newwrong.append((t, xs['v2'], xs['v3']))
        elif not e2 and not e3:
            still.append((t, xs['v2'], xs['v3']))
    m1, e1_, a1 = met['v1']; m2, e2_, a2 = met['v2']; m3, e3_, a3 = met['v3']
    v2_changes = sum(1 for x in v3_items if x['v2_primary'] != x['kp_primary'])
    target_ok = m3 / n >= 0.90 and e3_ >= e2_
    # Top 错误类型统计
    err_types = collections.Counter()
    for t, x2, x3 in still + newwrong:
        if not x3['kp_primary']:
            err_types['v3 空/vocab_gap'] += 1
        elif x3['kp_primary'].split('_')[1] != t['teacher_module'].split('_')[1]:
            err_types['模块误判'] += 1
        else:
            err_types['同模块考点偏差'] += 1
    L = ['---', 'type: report', 'title: 教材映射 v3（section→kp 细化）', 'updated: 2026-11-06',
         'status: pilot-v3', '---', '',
         '# 教材映射 v3 · section→kp 细化 pilot', '',
         '> 映射阶段**不读取教师标签**；教师标签只在 v3 生成后用于评估（分母 88）。',
         '> 未调 OCR、未写 PG/vault、未 commit。', '',
         '## 1. v3 规则', '',
         '1. chapter 层：用 chapter_num → 允许模块，限制候选 kp 不跨章；',
         '2. section 层：从 section 标题构建 `section→候选 kp` 词典（词表关键词 + 章节标题；人工 override 仅依据课标/节名，不看教师标签）；',
         '3. 正文层：120 词表关键词打分；词典候选 +4、section 标题 +2×分、正文分；',
         '4. secondary：仅保留跨模块且证据 ≥3 的候选（v2 any 下降的修正：不让同模块泛化项挤进 secondary）；',
         '5. non_content / vocab_gap 规则不变。', '',
         f'- section 词典条目：**{len(dictionary)}**；有候选的：**{sum(1 for v in dictionary.values() if v["candidates"])}**', '',
         '## 2. 评估（教师标签，分母 %d）' % n, '',
         '| 指标 | v1 | v2 | v3 | v2→v3 |', '| --- | --- | --- | --- | --- |',
         f'| 模块一致 | {m1}/{n}={m1/n*100:.1f}% | {m2}/{n}={m2/n*100:.1f}% | **{m3}/{n}={m3/n*100:.1f}%** | {m3-m2:+d} |',
         f'| 考点 exact | {e1_}/{n}={e1_/n*100:.1f}% | {e2_}/{n}={e2_/n*100:.1f}% | **{e3_}/{n}={e3_/n*100:.1f}%** | {e3_-e2_:+d} |',
         f'| 含 secondary | {a1}/{n}={a1/n*100:.1f}% | {a2}/{n}={a2/n*100:.1f}% | **{a3}/{n}={a3/n*100:.1f}%** | {a3-a2:+d} |', '',
         f'- primary 变化：**{v2_changes}** 块；相对 v2 修正 **{len(fixed)}**、仍错 **{len(still)}**、新错 **{len(newwrong)}**。', '',
         '## 3. 逐块 diff', '',
         '### 3.1 v2 错 → v3 对（section 词典修正）', '',
         '| block_id | 教师 | v2 | v3 | 章节/节 |', '| --- | --- | --- | --- | --- |']
    for t, x2, x3 in fixed[:30]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x2["kp_primary"]}` | `{x3["kp_primary"]}` | '
                 f'{x3.get("chapter","")}/{x3.get("section","")} |')
    L += ['', '### 3.2 v3 仍错', '', '| block_id | 教师 | v2 | v3 | 备注 |', '| --- | --- | --- | --- | --- |']
    for t, x2, x3 in still[:30]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x2["kp_primary"]}` | `{x3["kp_primary"]}` | {t["note"][:60]} |')
    L += ['', '### 3.3 v3 新错', '', '| block_id | 教师 | v2 | v3 | 备注 |', '| --- | --- | --- | --- | --- |']
    for t, x2, x3 in newwrong[:30]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x2["kp_primary"]}` | `{x3["kp_primary"]}` | {t["note"][:60]} |')
    L += ['', '## 4. 错误类型', '', '| 类型 | 数量 |', '| --- | --- |']
    for k, v in err_types.most_common():
        L.append(f'| {k} | {v} |')
    L += ['', '## 5. 结论', '',
          f'- **达标判断：模块≥90% 且 exact 不降（≥ v2 {e2_}）：{"✅ 达到" if target_ok else "❌ 未达到"}**',
          f'  - v3 模块 {m3/n*100:.1f}%（目标 ≥90%），exact {e3_}/{n}（v2 {e2_}）。',
          '- v3 的 section 词典对"节标题明确"的块有修正作用，但章末小结/跨节混排块仍受正文多主题干扰；'
          'secondary 的跨模块证据门槛已避免 v2 式虚高。',
          '- 结论：' + ('**可进入全量 1797**（建议先抽 10% 复核）。' if target_ok else
                        '**暂不能全量**：还缺“章末小结/跨节混排”的专门规则、部分 section→kp 词典补全和更细的正文特征（如例题/习题题干模板）。'),
          '', '---', '', '> 产物：`section_kp_dictionary.json`、`mapped_100_v3.json`、`mapped_100_v3_batch.txt`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[v3] {len(v3_items)} 块；词典 {len(dictionary)}；教师分母 {n}：'
          f'模块 {m1}→{m2}→{m3}；exact {e1_}→{e2_}→{e3_}；any {a1}→{a2}→{a3}；'
          f'固定/仍/新 {len(fixed)}/{len(still)}/{len(newwrong)}；达标={target_ok}')
    print(f'报告：{REPORT}')


if __name__ == '__main__':
    main()
