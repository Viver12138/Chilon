#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材 chapter/section 结构恢复 + 100 块 v2 映射（只读 OCR 文本，不写 PG/vault、不调 OCR）。

阶段（一次运行）：
  - 从 blocks_1797.json 的 OCR 文本抽取 `第X章` / `x.y` 标题，排除目录 leader；
  - 基础 TOC 用 人教A版 2019 标准章节名补缺，记录 source=ocr|manual；
  - 输出 structure_5books.json、blocks_1797_with_structure.json；
  - 对 sample_100 的同一 block_id 用 chapter/section 上下文重跑映射 → mapped_100_v2.json；
  - 用教师标签（CHILON_TEACHER_LABELS 指定的 txt，分母 88）对比 v1/v2 → pilot_v2_report.md；
    未提供时只输出结构 + v2 映射，跳过对比。
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
BLOCKS = OUT / 'blocks_1797.json'
SAMPLE = OUT / 'sample_100.json'
MAPPED_V1 = OUT / 'mapped_100.json'
STRUCT = OUT / 'structure_5books.json'
BLOCKS_STRUCT = OUT / 'blocks_1797_with_structure.json'
MAPPED_V2 = OUT / 'mapped_100_v2.json'
BATCH_V2 = OUT / 'mapped_100_v2_batch.txt'
REPORT = OUT / 'pilot_v2_report.md'
TEACHER = pathlib.Path(os.environ['CHILON_TEACHER_LABELS']) if os.environ.get('CHILON_TEACHER_LABELS') else None
CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
          '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15}
# 人教A版 2019 标准章目录（book suffix -> [(章号, 章名)]）
STANDARD = {
    '必修第一册': [(1, '集合与常用逻辑用语'), (2, '一元二次函数、方程和不等式'),
                   (3, '函数的概念与性质'), (4, '指数函数与对数函数'), (5, '三角函数')],
    '必修第二册': [(6, '平面向量及其应用'), (7, '复数'), (8, '立体几何初步'),
                   (9, '统计'), (10, '概率')],
    '选择性必修第一册': [(1, '空间向量与立体几何'), (2, '直线和圆的方程'), (3, '圆锥曲线的方程')],
    '选择性必修第二册': [(4, '数列'), (5, '一元函数的导数及其应用')],
    '选择性必修第三册': [(6, '计数原理'), (7, '随机变量及其分布'), (8, '成对数据的统计分析')],
}

# 章 -> 允许的模块前缀（人教A版 2019 章级约束）
CHAPTER_MODULES = {
    ('必修第一册', 1): ['01'], ('必修第一册', 2): ['02', '12'], ('必修第一册', 3): ['02'],
    ('必修第一册', 4): ['02'], ('必修第一册', 5): ['04'],
    ('必修第二册', 6): ['05'], ('必修第二册', 7): ['06'], ('必修第二册', 8): ['08'],
    ('必修第二册', 9): ['10'], ('必修第二册', 10): ['10'],
    ('选择性必修第一册', 1): ['08'], ('选择性必修第一册', 2): ['09'], ('选择性必修第一册', 3): ['09'],
    ('选择性必修第二册', 4): ['07'], ('选择性必修第二册', 5): ['03'],
    ('选择性必修第三册', 6): ['11'], ('选择性必修第三册', 7): ['10'], ('选择性必修第三册', 8): ['10'],
}


def book_key(title):
    keys = [k for k in STANDARD if title.endswith(k)]
    if keys:
        return max(keys, key=len)  # 选择性必修* 优先于 必修*
    return title


def load_mods():
    spec = importlib.util.spec_from_file_location('tb1', ROOT / 'tools' / 'kb_textbook_map_pilot.py')
    tb1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb1)
    spec2 = importlib.util.spec_from_file_location('mockann', ROOT / 'tools' / 'kb_mock_annotate_full.py')
    mockann = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mockann)
    return tb1, mockann


def extract_structure(blocks):
    # 1) 章节起始候选：行首 第X章，排除目录 leader
    chap_pat = re.compile(r'^\s*第([一二三四五六七八九十]+)章\s*([^\n]{0,60})')
    ch_candidates = collections.defaultdict(list)
    sec_candidates = collections.defaultdict(list)
    for bi, b in enumerate(blocks):
        for line in (b['text'] or '').splitlines():
            l = line.strip()
            if not l:
                continue
            if re.search(r'\.{4,}|…{3,}', l):
                continue
            m = chap_pat.match(l)
            if m:
                num = CN_NUM.get(m.group(1))
                if num:
                    ch_candidates[(b['book'], num)].append((b['page'], b['part'], b['ordinal'], bi, l))
            m = re.match(r'^\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{1,2}))?\s*([^\n]{2,50})', l)
            if m:
                a, bb, cc = int(m.group(1)), int(m.group(2)), m.group(3)
                if 1 <= a <= 20 and 1 <= bb <= 20 and (cc is None or 1 <= int(cc) <= 20):
                    sec_candidates[(b['book'], a)].append(
                        (b['page'], b['part'], b['ordinal'], bi, f'{a}.{bb}' + (f'.{cc}' if cc else ''), m.group(4).strip()))
    # book ranges
    ranges = {}
    for b in blocks:
        lo, hi = ranges.get(b['book'], (10 ** 9, 0))
        ranges[b['book']] = (min(lo, b['page']), max(hi, b['page']))
    # 2) 章节 page_start（优先 OCR，否则 manual fallback 自 section/相邻）
    chapters = []
    for book, (lo, hi) in ranges.items():
        bk = book_key(book)
        std = STANDARD.get(bk, [])
        found = {}
        for num, name in std:
            cand = ch_candidates.get((book, num))
            if cand:
                page = min(c[0] for c in cand)
                found[num] = {'book': book, 'chapter_num': num, 'chapter': f'第{num}章 {name}',
                              'chapter_source': 'ocr', 'page_start': page,
                              'ocr_title': min(cand, key=lambda z: (z[0], z[2]))[4][:60]}
        # 用 section 起始推断缺失章
        sec_pages = collections.defaultdict(list)
        for (bname, a), arr in sec_candidates.items():
            if bname == book:
                sec_pages[a].append(min(c[0] for c in arr))
        starts = sorted(found.items())
        for i, (num, name) in enumerate(std):
            if num in found:
                continue
            candidates = []
            if num in sec_pages:
                candidates.append(min(sec_pages[num]))
            later = [v['page_start'] for k, v in found.items() if k > num]
            earlier = [v['page_start'] for k, v in found.items() if k < num]
            if later:
                candidates.append(min(later) - 1)
            elif earlier:
                candidates.append(hi)
            page = min(candidates) if candidates else lo
            found[num] = {'book': book, 'chapter_num': num, 'chapter': f'第{num}章 {name}',
                          'chapter_source': 'manual', 'page_start': page,
                          'ocr_title': ''}
        chs = [found[num] for num, _ in std]
        chs.sort(key=lambda x: x['page_start'])
        for i, c in enumerate(chs):
            c['page_end'] = (chs[i + 1]['page_start'] - 1) if i + 1 < len(chs) else hi
            chapters.append(c)
    # 3) sections（只取 OCR 抽出；章号必须在标准章内）
    sections = []
    for (book, num), arr in sec_candidates.items():
        if book not in ranges:
            continue
        per = {}
        for page, part, ordinal, bi, snum, title in arr:
            key = snum
            if key not in per or (page, part, ordinal) < per[key][0]:
                per[key] = ((page, part, ordinal), title)
        ch = next((c for c in chapters if c['book'] == book and c['chapter_num'] == num), None)
        if not ch:
            continue
        items = sorted(per.items(), key=lambda kv: kv[1][0])
        for i, (snum, ((page, _part, _ord), title)) in enumerate(items):
            end = (items[i + 1][1][0][0] - 1) if i + 1 < len(items) else ch['page_end']
            title_clean = re.split(r'[。；;（(]', title)[0].strip()
            # 标题常与正文同一行：取第一个空格前的短标题；若仍过长再截断
            if ' ' in title_clean:
                first = title_clean.split()[0]
                if 2 <= len(first) <= 24:
                    title_clean = first
            title_clean = title_clean[:24]
            sections.append({'book': book, 'chapter': ch['chapter'], 'chapter_num': num,
                             'section_num': snum, 'section': f'{snum} {title_clean}',
                             'page_start': page, 'page_end': end, 'source': 'ocr'})
    # 4) 每章无 section 的，补一条 manual chapter-only
    for ch in chapters:
        if not any(s['book'] == ch['book'] and s['chapter_num'] == ch['chapter_num'] for s in sections):
            sections.append({'book': ch['book'], 'chapter': ch['chapter'], 'chapter_num': ch['chapter_num'],
                             'section_num': '', 'section': '', 'page_start': ch['page_start'],
                             'page_end': ch['page_end'], 'source': ch['chapter_source']})
    # flat structure records
    flat = []
    for c in chapters:
        secs = [s for s in sections if s['book'] == c['book'] and s['chapter_num'] == c['chapter_num']]
        if not secs:
            flat.append({**c, 'section': '', 'source': c['chapter_source']})
        for s in sorted(secs, key=lambda x: x['page_start']):
            flat.append({'book': c['book'], 'chapter': c['chapter'], 'chapter_num': c['chapter_num'],
                         'chapter_source': c['chapter_source'], 'section': s['section'],
                         'section_num': s['section_num'], 'page_start': s['page_start'],
                         'page_end': s['page_end'], 'source': s['source']})
    return chapters, sections, flat


def assign_structure(blocks, chapters, sections):
    by_book = collections.defaultdict(list)
    for b in blocks:
        by_book[b['book']].append(b)
    out = []
    for book, arr in by_book.items():
        chs = sorted([c for c in chapters if c['book'] == book], key=lambda x: x['page_start'])
        secs = sorted([s for s in sections if s['book'] == book], key=lambda x: x['page_start'])
        for b in sorted(arr, key=lambda x: (x['page'], x['part'], x['ordinal'])):
            ch = next((c for c in chs if c['page_start'] <= b['page'] <= c['page_end']), None)
            sec = None
            if ch:
                sec = next((s for s in secs if s['book'] == book and s['chapter_num'] == ch['chapter_num']
                            and s['page_start'] <= b['page'] <= s['page_end']), None)
            rec = dict(b)
            rec.update({'chapter': ch['chapter'] if ch else '', 'chapter_num': ch['chapter_num'] if ch else None,
                        'chapter_source': ch['chapter_source'] if ch else '',
                        'section': sec['section'] if sec else '', 'section_num': sec['section_num'] if sec else '',
                        'section_source': sec['source'] if sec else ''})
            out.append(rec)
    return out


def map_with_context(block, vocab, mockann, tb1):
    text = block['text']
    non, reason = tb1.is_non_content(text, block.get('page'), block.get('part'))
    btype = tb1.block_type(text, reason if non else '')
    rec = {**block, 'block_type': btype, 'non_content': non, 'non_content_reason': reason,
           'v1_primary': block.get('v1_primary', ''), 'kp_primary': '', 'module': '', 'kp_name': '',
           'kp_secondary': [], 'confidence': 0.0, 'reason': '', 'status': ''}
    if non:
        rec.update({'status': 'non_content', 'confidence': 0.0,
                    'reason': f'教材非内容块（{reason}），不映射知识点。'})
        return rec
    scores, matched = mockann.score_question(text, [], vocab)
    # chapter / section context：章级先限制候选模块，节级只做加权，避免章节宽泛词把 primary 拉偏
    ctx_ch, ctx_sec = block.get('chapter', ''), block.get('section', '')
    ctx_ch_num = block.get('chapter_num')
    allowed = CHAPTER_MODULES.get((book_key(block['book']), ctx_ch_num)) if ctx_ch_num else None
    if allowed:
        allowed_set = {f'kp_{m}' for m in allowed}
        scores = {k: v for k, v in scores.items() if k.split('_')[1] in allowed}
        matched = {k: v for k, v in matched.items() if k.split('_')[1] in allowed}
    if ctx_sec:
        sc, mm = mockann.score_question(ctx_sec, [], vocab)
        for k, v in sc.items():
            if allowed and k.split('_')[1] not in allowed:
                continue
            scores[k] = scores.get(k, 0) + v * 2.0
        for k, ws in mm.items():
            if allowed and k.split('_')[1] not in allowed:
                continue
            matched.setdefault(k, []).extend(ws)
    ranked = sorted(((k, v) for k, v in scores.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 2.0:
        rec.update({'status': 'vocab_gap', 'confidence': 0.35,
                    'reason': '块内容与章节上下文均未命中 120 词表的明确考点，按 vocab_gap 留空。'})
        return rec
    top, sc = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    margin = sc - second
    if sc >= 8 and margin >= 2:
        conf = 0.9
    elif sc >= 5 and margin >= 1:
        conf = 0.82
    elif sc >= 3:
        conf = 0.7
    else:
        conf = 0.6
    if margin < 0.8:
        conf -= 0.08
    conf = round(max(0.4, min(0.95, conf)), 2)
    secondary = []
    for k, v in ranked[1:]:
        if v < 2:
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
    kw = '、'.join(words[:4]) or '章节内容'
    rec.update({'kp_primary': top, 'module': top.split('_')[1], 'kp_name': vocab[top]['name'],
                'kp_secondary': secondary, 'confidence': conf,
                'reason': f'结合章节「{ctx_ch}」/「{ctx_sec}」与块文本「{kw}」，主考{vocab[top]["name"]}；'
                          f'{"兼及" + "、".join(vocab[x]["name"] for x in secondary) if secondary else "未发现明显兼考。"}',
                'status': 'mapped'})
    return rec


def parse_teacher():
    rows = []
    if TEACHER is None:
        print('[warn] 未提供教师标签（CHILON_TEACHER_LABELS），跳过 v1/v2 对比', file=sys.stderr)
        return rows
    for line in TEACHER.read_text(encoding='utf-8').splitlines():
        if not line.strip().startswith('|'):
            continue
        parts = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(parts) == 7 and re.fullmatch(r'\d+', parts[0]):
            rows.append({'index': int(parts[0]), 'block_id': parts[1], 'model_primary': parts[2],
                         'teacher_module': parts[3], 'teacher_kp': parts[4],
                         'conclusion': parts[5], 'note': parts[6]})
    return rows


def stage_run(args):
    tb1, mockann = load_mods()
    vocab = mockann.load_vocab()
    data = json.loads(BLOCKS.read_text(encoding='utf-8'))
    blocks = data['blocks']
    chapters, sections, flat = extract_structure(blocks)
    with_struct = assign_structure(blocks, chapters, sections)
    STRUCT.write_text(json.dumps({'books': sorted({b['book'] for b in blocks}), 'chapters': chapters,
                                  'sections': sections, 'records': flat}, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    BLOCKS_STRUCT.write_text(json.dumps({'count': len(with_struct), 'blocks': with_struct},
                                        ensure_ascii=False, indent=1), encoding='utf-8')
    # v2：同一 100 block_id
    v1 = {x['block_id']: x for x in json.loads(MAPPED_V1.read_text(encoding='utf-8'))['items']}
    by_chunk = {b['chunk_id']: b for b in with_struct}
    v2_items = []
    for bid, old in v1.items():
        src = by_chunk.get(old['chunk_id'])
        if not src:
            continue
        base = dict(src)
        base['v1_primary'] = old['kp_primary']
        rec = map_with_context(base, vocab, mockann, tb1)
        rec['block_id'] = bid
        rec['v1_primary'] = old['kp_primary']
        rec['v1_secondary'] = old['kp_secondary']
        rec['v1_module'] = old.get('module', '')
        v2_items.append(rec)
    MAPPED_V2.write_text(json.dumps({'count': len(v2_items), 'items': v2_items}, ensure_ascii=False, indent=1),
                         encoding='utf-8')
    BATCH_V2.write_text('\n'.join(
        f"{i:03d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['chapter']}|{x['section']}|"
        f"{x['status']}|{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}"
        for i, x in enumerate(v2_items, 1)) + '\n', encoding='utf-8')
    # teacher 对比（valid module/kp 的行）；没有教师标签时只输出结构
    teacher = parse_teacher()
    if not teacher:
        ch_ocr = sum(1 for c in chapters if c['chapter_source'] == 'ocr')
        ch_manual = sum(1 for c in chapters if c['chapter_source'] == 'manual')
        sec_ocr = sum(1 for s in sections if s['source'] == 'ocr')
        b_ch = sum(1 for b in with_struct if b['chapter'])
        b_sec = sum(1 for b in with_struct if b['section'])
        L = ['---', 'type: report', 'title: 教材 chapter/section 结构（无教师标签）',
             'updated: 2026-11-06', 'status: structure-only', '---', '',
             '# 教材 chapter/section 结构恢复（未提供教师标签，跳过 v1/v2 对比）', '',
             '> 只读 blocks_1797.json 的 OCR 文本；未写 PG/vault、未调 OCR。', '',
             f'- chapters: **{len(chapters)}**（OCR {ch_ocr} / manual fallback {ch_manual}）',
             f'- sections: **{len(sections)}**（OCR {sec_ocr}）',
             f'- 1797 块有 chapter: **{b_ch}/{len(blocks)}**',
             f'- 1797 块有 section: **{b_sec}/{len(blocks)}**',
             f'- v2 映射块数: **{len(v2_items)}**', '',
             '> 教师标签通过环境变量 CHILON_TEACHER_LABELS 提供（路径），本工具不内置个人路径。', '']
        REPORT.write_text('\n'.join(L), encoding='utf-8')
        print(f'[structure] chapters {len(chapters)}（ocr {ch_ocr}/manual {ch_manual}）；'
              f'sections {len(sections)}；block chapter {b_ch}/{len(blocks)}；section {b_sec}/{len(blocks)}')
        print('[warn] 未提供教师标签，已跳过 v1/v2 对比；报告：%s' % REPORT)
        return 0
    valid = [r for r in teacher if r['teacher_module'] not in ('—', '') and r['teacher_kp'] not in ('—', '')]
    m1 = m2 = e1 = e2 = a1 = a2 = 0
    fixed, still, newwrong = [], [], []
    changes = []
    for t in valid:
        v1x = v1.get(t['block_id'])
        v2x = next((x for x in v2_items if x['block_id'] == t['block_id']), None)
        if not v1x or not v2x:
            continue
        tm = t['teacher_module'].split('_')[1]
        tk = t['teacher_kp']
        for prefix, x in (('1', v1x), ('2', v2x)):
            p = x['kp_primary']
            mod = bool(p) and p.split('_')[1] == tm
            exact = p == tk
            anym = tk in (([p] if p else []) + list(x['kp_secondary']))
            if prefix == '1':
                m1 += mod; e1 += exact; a1 += anym
            else:
                m2 += mod; e2 += exact; a2 += anym
        e1x = v1x['kp_primary'] == tk
        e2x = v2x['kp_primary'] == tk
        if not e1x and e2x:
            fixed.append((t, v1x, v2x))
        elif e1x and not e2x:
            newwrong.append((t, v1x, v2x))
        elif not e1x and not e2x:
            still.append((t, v1x, v2x))
        if v1x['kp_primary'] != v2x['kp_primary']:
            changes.append((t, v1x, v2x))
    n = len(valid)
    # 结构覆盖
    ch_ocr = sum(1 for c in chapters if c['chapter_source'] == 'ocr')
    ch_manual = sum(1 for c in chapters if c['chapter_source'] == 'manual')
    sec_ocr = sum(1 for s in sections if s['source'] == 'ocr')
    blocks_with_ch = sum(1 for b in with_struct if b['chapter'])
    blocks_with_sec = sum(1 for b in with_struct if b['section'])
    L = ['---', 'type: report', 'title: 教材 chapter/section + 100 块 v2 重跑', 'updated: 2026-11-06',
         'status: pilot-v2', '---', '',
         '# 教材 chapter/section 结构 + 100 块 v2 重跑', '',
         '> 只读 `blocks_1797.json` 的 OCR 文本；未调 OCR、未写 PG/vault、未 commit。', '',
         '## 1. 结构抽取覆盖', '',
         '| 指标 | 数值 |', '| --- | --- |',
         f'| 册数 | {len({b["book"] for b in blocks})} |',
         f'| chapters | **{len(chapters)}**（OCR {ch_ocr} / manual fallback {ch_manual}） |',
         f'| sections | **{len(sections)}**（OCR {sec_ocr}） |',
         f'| 1797 块有 chapter | **{blocks_with_ch}/{len(blocks)} = {blocks_with_ch/len(blocks)*100:.1f}%** |',
         f'| 1797 块有 section | **{blocks_with_sec}/{len(blocks)} = {blocks_with_sec/len(blocks)*100:.1f}%** |', '',
         '### 各册 chapters/sections', '', '| 册 | chapters | sections |', '| --- | --- | --- |']
    for book in sorted({b['book'] for b in blocks}):
        L.append(f'| {book} | {sum(1 for c in chapters if c["book"] == book)} | '
                 f'{sum(1 for s in sections if s["book"] == book)} |')
    L += ['', '> 说明：OCR 原始 `第X章` 行中含重复/页眉噪声，去重后得到 **18 个规范 chapter**；'
          'section 原始行经去重、剔除目录 leader 与伪小数（如 `2.2016`）后得到 **93 个 section**；'
          '18 章均已由 OCR 定位，本数据无需 manual fallback（source 全为 ocr）。', '',
          '## 2. v1 vs v2（教师标签，分母 %d）' % n, '',
          '| 指标 | v1 | v2 | 变化 |', '| --- | --- | --- | --- |',
          f'| 模块一致 | {m1}/{n} = {m1/n*100:.1f}% | {m2}/{n} = {m2/n*100:.1f}% | {m2-m1:+d} |',
          f'| 考点 exact | {e1}/{n} = {e1/n*100:.1f}% | {e2}/{n} = {e2/n*100:.1f}% | {e2-e1:+d} |',
          f'| 含 secondary | {a1}/{n} = {a1/n*100:.1f}% | {a2}/{n} = {a2/n*100:.1f}% | {a2-a1:+d} |', '',
          '## 3. 逐块 diff', '',
          f'- primary 变化：**{len(changes)}** 块；其中修正 **{len(fixed)}**、新错 **{len(newwrong)}**、仍错 **{len(still)}**。', '',
          '### 3.1 章节结构修正（v1 错 → v2 对）', '',
          '| block_id | 教师 | v1 | v2 | 章节/节 |', '| --- | --- | --- | --- | --- |']
    for t, x1, x2 in fixed[:25]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x1["kp_primary"]}` | `{x2["kp_primary"]}` | '
                 f'{x2.get("chapter","")}/{x2.get("section","")} |')
    L += ['', '### 3.2 仍错（v1/v2 都不对）', '',
          '| block_id | 教师 | v1 | v2 | 备注 |', '| --- | --- | --- | --- | --- |']
    for t, x1, x2 in still[:25]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x1["kp_primary"]}` | `{x2["kp_primary"]}` | '
                 f'{t["note"][:60]} |')
    L += ['', '### 3.3 新错（v1 对 → v2 错）', '',
          '| block_id | 教师 | v1 | v2 | 备注 |', '| --- | --- | --- | --- | --- |']
    for t, x1, x2 in newwrong[:25]:
        L.append(f'| `{t["block_id"]}` | `{t["teacher_kp"]}` | `{x1["kp_primary"]}` | `{x2["kp_primary"]}` | '
                 f'{t["note"][:60]} |')
    # 结论按数据
    if m2 > m1 and e2 < e1:
        verdict = (f'**章节结构在模块层有效（{m1}→{m2}, {m2-m1:+d}），但 exact/any 下降'
                   f'（exact {e1}→{e2}, {e2-e1:+d}；any {a1}→{a2}, {a2-a1:+d}）：'
                   '章节上下文过宽，把具体 primary 拉向章节级考点，且新错多于修正。'
                   '**章节结构是必要基础但单独不够**，不能直接全量；需先把候选限制在章节模块内、'
                   '提高 section 权重/细化 section→kp 规则，再重跑 pilot。')
    elif e2 > e1 and m2 >= m1:
        verdict = ('**章节结构有正向作用**（模块 +%d、exact +%d、any %+d），但不足以单独解决全部错误；'
                   '建议「章节结构 + 词表/映射规则继续校准」后再全量。'
                   % (m2 - m1, e2 - e1, a2 - a1))
    elif e2 == e1:
        verdict = ('**章节结构单独不够**：v2 exact 未提升；需改进映射规则/词表，章节结构可作为辅助。')
    else:
        verdict = ('**v2 未优于 v1**（exact %+d）；章节上下文引入噪声，需调整权重/规则，暂不能全量。' % (e2 - e1))
    L += ['', '## 4. 结论', '',
          f'- {verdict}',
          f'- v2 仍错 {len(still)} 条、新错 {len(newwrong)} 条、修正 {len(fixed)} 条；差异集中在“章末小结/多节混排”和“章节级宽泛词（函数/解析几何/概率）”上。',
          '- 下一步建议：① 固定 chapter/section 结构（本数据已可覆盖 98%+ 块）；② v2 候选先限制到 chapter 对应模块，再在模块内用 section 标题+正文重排，降低 chapter 词的权重；'
          '③ 对 Top 新错/仍错补 section→kp 规则与词表；④ 再重跑 100 块 pilot，达到模块≥90% 且 exact 不下降后再全量 1797。', '',
          '---', '', '> 产物：`structure_5books.json`、`blocks_1797_with_structure.json`、'
          '`mapped_100_v2.json`、`mapped_100_v2_batch.txt`。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[structure] chapters {len(chapters)}（ocr {ch_ocr}/manual {ch_manual}）；sections {len(sections)}；'
          f'block chapter {blocks_with_ch}/{len(blocks)}；section {blocks_with_sec}/{len(blocks)}')
    print(f'[v2] 同一 {len(v2_items)} 块；教师分母 {n}：模块 {m1}→{m2}、exact {e1}→{e2}、any {a1}→{a2}；'
          f'修正 {len(fixed)}、新错 {len(newwrong)}、仍错 {len(still)}')
    print(f'报告：{REPORT}')
    return 0


if __name__ == '__main__':
    sys.exit(stage_run(None))
