#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""教材块映射 100 块 pilot（只读 PG，不写 PG/vault、不调 OCR）。

阶段：
  --stage prepare  从 PG textbook 1797 chunks 抽样 100 块（5 册 ×20，页跨度均匀，seed=20261106），
                   生成 blocks_1797.json / mapped_100.json / mapped_100_batch.txt / pilot_report.md
  --stage xlsx     读取 mapped_100.json，生成教师核对 xlsx（本阶段仅需 openpyxl，可用系统 python 运行）

映射规则：120 词表关键词 + 教材章节标题 + 块类型；封面/目录/纯页码/版权/前言 → non_content；
内容块找不到合适词条 → vocab_gap（primary 留空，不硬塞）。

词表默认 `corpus/eval/kp_vocab.md`（仓库内副本），可用 CHILON_KP_VOCAB 覆盖；
xlsx 副本默认不写个人目录，需要时用 `--xlsx-copy` 或 CHILON_XLSX_COPY。
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'var' / 'textbook_mapping'
OUT.mkdir(parents=True, exist_ok=True)
BLOCKS = OUT / 'blocks_1797.json'
SAMPLE = OUT / 'sample_100.json'
MAPPED = OUT / 'mapped_100.json'
BATCH = OUT / 'mapped_100_batch.txt'
REPORT = OUT / 'pilot_report.md'
XLSX = OUT / '教材块映射抽检_100块_2026-11-06.xlsx'
CONTAINER = 'chilon-pg-corpus'
DB_HOST, DB_PORT, DB_NAME, DB_USER = '127.0.0.1', 55495, 'chilon', 'postgres'
SEED = 20261106
BOOKS_EXPECTED = 5
CHUNKS_EXPECTED = 1797
VOCAB_MD = pathlib.Path(os.environ.get('CHILON_KP_VOCAB') or (ROOT / 'corpus' / 'eval' / 'kp_vocab.md'))


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


def load_tools():
    spec = importlib.util.spec_from_file_location('mockann', ROOT / 'tools' / 'kb_mock_annotate_full.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fetch_blocks():
    import psycopg
    conn = psycopg.connect(db_url())
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id::text, s.title, c.id::text, c.chunk_key, c.ordinal,
               (c.locator->>'page')::int, (c.locator->>'part')::int, c.text_content
        FROM knowledge_chunks c
        JOIN knowledge_document_versions dv ON dv.id=c.document_version_id
        JOIN knowledge_sources s ON s.id=dv.source_id
        WHERE s.source_type='textbook'
        ORDER BY s.title, (c.locator->>'page')::int, (c.locator->>'part')::int, c.ordinal
    """)
    rows = cur.fetchall()
    conn.close()
    if len(rows) != CHUNKS_EXPECTED:
        raise SystemExit(f'教材 chunk {len(rows)} ≠ {CHUNKS_EXPECTED}')
    books = []
    blocks = []
    for r in rows:
        sid, title, chunk_id, key, ordinal, page, part, text = r
        if title not in books:
            books.append(title)
        blocks.append({'source_id': sid, 'book': title, 'chunk_id': chunk_id,
                       'chunk_key': key, 'ordinal': ordinal,
                       'page': page, 'part': part, 'text': text or ''})
    if len(books) != BOOKS_EXPECTED:
        raise SystemExit(f'教材册数 {len(books)} ≠ 5')
    return books, blocks


def is_non_content(text, page, part):
    s = (text or '').strip()
    t = re.sub(r'\s+', '', s)
    if not t:
        return True, '空白'
    if re.fullmatch(r'[0-9\-—–.·、，,;；:：/\\a-zA-Z\s]{1,12}', t):
        return True, '纯页码/符号'
    if '目录' in t and (t.count('.....') >= 3 or t.count('……') >= 3):
        return True, '目录'
    if page is not None and page <= 3 and '普通高中教科书' in t and len(t) < 220:
        return True, '封面'
    if re.search(r'ISBN|版权所有|著作权|开本|印张|定价|责任编辑|主编：|主编:', t):
        return True, '版权页'
    if re.search(r'主编寄语|本册导引|前言|序言', t) and len(t) < 1200:
        return True, '前言/导引'
    if '人民教育出版社' in t and ('编著' in t or '课程教材研究所' in t) and len(t) < 600:
        return True, '版权页'
    return False, ''


def block_type(text, non_content_reason=''):
    if non_content_reason:
        return non_content_reason
    t = text or ''
    if re.search(r'^\s*【?定义】?', t) or '叫做' in t or '称为' in t:
        return '定义/概念'
    if '定理' in t or '性质' in t or '公式' in t:
        return '定理/性质/公式'
    if re.search(r'\n?\s*例\s*\d', t) or '例题' in t:
        return '例题'
    if '练习' in t or '习题' in t or '复习参考题' in t:
        return '习题'
    return '正文'


def map_block(block, vocab, mockann):
    text = block['text']
    non, reason = is_non_content(text, block['page'], block['part'])
    btype = block_type(text, reason if non else '')
    rec = {**block, 'block_id': f"TB-{block['page']:04d}-{block['part']}-{block['chunk_key']}",
           'block_type': btype, 'non_content': non, 'non_content_reason': reason,
           'kp_primary': '', 'module': '', 'kp_name': '', 'kp_secondary': [], 'confidence': 0.0,
           'reason': '', 'status': ''}
    if non:
        rec.update({'status': 'non_content', 'confidence': 0.0,
                    'reason': f'教材非内容块（{reason}），不映射知识点。'})
        return rec
    # 章节标题增强：匹配 "1.1 集合的概念" 一类
    scores, matched = mockann.score_question(text, [], vocab)
    heads = re.findall(r'(?m)^\s*(\d+(?:\.\d+)+)\s*([^\n]{2,38})', text)
    for _num, head in heads[:12]:
        hs, hm = mockann.score_question(head, [], vocab)
        for k, v in hs.items():
            scores[k] += v * 1.5
        for k, ws in hm.items():
            matched[k].extend(ws)
    ranked = sorted(((k, v) for k, v in scores.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < 2.0:
        rec.update({'status': 'vocab_gap', 'confidence': 0.35,
                    'reason': '块内容未命中 120 词表的明确考点词，按 vocab_gap 留空，不硬塞。'})
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
    rec.update({'kp_primary': top, 'module': top.split('_')[1],
                'kp_name': vocab[top]['name'],
                'kp_secondary': secondary, 'confidence': conf,
                'reason': f'教材块（{btype}）出现「{kw}」，主考{vocab[top]["name"]}；'
                          f'{"兼及" + "、".join(vocab[x]["name"] for x in secondary) if secondary else "未发现明显兼考。"}',
                'status': 'mapped'})
    return rec


def sample_blocks(books, blocks):
    import random
    rng = random.Random(SEED)
    by_book = collections.defaultdict(list)
    for b in blocks:
        by_book[b['book']].append(b)
    sample = []
    for book in books:
        arr = sorted(by_book[book], key=lambda x: (x['page'], x['part'], x['ordinal']))
        pages = sorted({b['page'] for b in arr})
        # 页跨度均匀的 20 个页目标
        if len(pages) >= 20:
            idxs = sorted({round(i * (len(pages) - 1) / 19) for i in range(20)})
            targets = [pages[i] for i in idxs]
        else:
            targets = pages[:]
        chosen = []
        for p in targets:
            chunks = [b for b in arr if b['page'] == p]
            chosen.append(rng.choice(chunks))
        # 补足到 20（页数不足时）
        while len(chosen) < 20:
            b = rng.choice(arr)
            if b not in chosen:
                chosen.append(b)
        # 强制包含封面/目录（替换最后两个，保持 20）
        def replace_with(special, label):
            if not special:
                return
            if any(x['page'] == special['page'] and x['chunk_key'] == special['chunk_key'] for x in chosen):
                for x in chosen:
                    if x['page'] == special['page'] and x['chunk_key'] == special['chunk_key']:
                        x['_sample_forced'] = label
                return
            chosen[-1] = special
            chosen[-1]['_sample_forced'] = label
        cover = next((b for b in arr if is_non_content(b['text'], b['page'], b['part'])[1] == '封面'), None)
        toc = next((b for b in arr if is_non_content(b['text'], b['page'], b['part'])[1] == '目录'), None)
        replace_with(cover, '封面')
        replace_with(toc, '目录')
        for b in chosen[:20]:
            sample.append(b)
    return sample[:100]


REPLACE_TARGETS = [
    {'book': '普通高中教科书·数学（A版）必修第二册', 'page': 221, 'part': 1,
     'chunk_key': 'p0221-01', 'legacy_id': 'TB-0221-1-p0221-01'},
    {'book': '普通高中教科书·数学（A版）选择性必修第一册', 'page': 18, 'part': 2,
     'chunk_key': 'p0018-02', 'legacy_id': 'TB-0018-2-p0018-02'},
]


def make_block_id(rec, book_idx):
    rec['legacy_block_id'] = f"TB-{rec['page']:04d}-{rec['part']}-{rec['chunk_key']}"
    rec['block_id'] = f"TB-B{book_idx[rec['book']]}-{rec['page']:04d}-{rec['part']}-{rec['chunk_key']}"


def replace_problem_blocks(mapped, blocks, vocab, mockann, book_idx):
    """替换空文本/指定 block：同册、近页、非空、未抽中，优先正文/定理/例题/定义。"""
    type_rank = {'正文': 0, '定理/性质/公式': 0, '例题': 0, '定义/概念': 0, '习题': 1}
    used = {x['chunk_id'] for x in mapped}
    replacements = []
    for idx, target in enumerate(list(mapped)):
        hit = any(t['book'] == target['book'] and t['page'] == target['page']
                  and t['part'] == target['part'] and t['chunk_key'] == target['chunk_key']
                  for t in REPLACE_TARGETS)
        if target['text'].strip() and not hit:
            continue
        same = [b for b in blocks
                if b['source_id'] == target['source_id']
                and b['chunk_id'] not in used
                and (b['text'] or '').strip()
                and not is_non_content(b['text'], b['page'], b['part'])[0]]
        if not same:
            continue
        same.sort(key=lambda b: (type_rank.get(block_type(b['text']), 2),
                                 abs((b['page'] or 0) - (target['page'] or 0)),
                                 b['page'], b['part'], b['ordinal']))
        pick = same[0]
        new = map_block(pick, vocab, mockann)
        make_block_id(new, book_idx)
        new['_added_by_replacement'] = True
        new['replaced_from'] = target['legacy_block_id']
        used.add(pick['chunk_id'])
        mapped[idx] = new
        replacements.append({'old_block_id': target['legacy_block_id'],
                             'old_book': target['book'], 'old_page': target['page'],
                             'old_type': target['block_type'],
                             'new_block_id': new['block_id'], 'new_book': new['book'],
                             'new_page': new['page'], 'new_type': new['block_type'],
                             'reason': f'原表显示完整原文为空（PG 原文以 = 开头被 Excel 当公式）；'
                                       f'同册近页（页距 {abs((pick["page"] or 0)-(target["page"] or 0))}），'
                                       f'替换为未抽中的非空内容块 {new["block_type"]}'})
    return mapped, replacements


def stage_prepare(args):
    vocab = load_tools().load_vocab()
    mockann = load_tools()
    # 模块前缀 -> 模块ID/名称
    mod_map = {}
    for line in VOCAB_MD.read_text(encoding='utf-8').splitlines():
        mm = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if mm:
            name = re.split(r'（', mm.group(1))[0].strip()
            mod_map[mm.group(2).split('_')[1]] = {'id': mm.group(2), 'name': name}
    books, blocks = fetch_blocks()
    BLOCKS.write_text(json.dumps({'count': len(blocks), 'books': books, 'blocks': blocks},
                                 ensure_ascii=False, indent=1), encoding='utf-8')
    sample = sample_blocks(books, blocks)
    SAMPLE.write_text(json.dumps({'seed': SEED, 'count': len(sample),
                                  'blocks': [{k: v for k, v in b.items() if not k.startswith('_')}
                                             for b in sample]}, ensure_ascii=False, indent=1),
                      encoding='utf-8')
    mapped = [map_block(b, vocab, mockann) for b in sample]
    book_idx = {book: i + 1 for i, book in enumerate(books)}
    for rec in mapped:
        make_block_id(rec, book_idx)
    mapped, replacements = replace_problem_blocks(mapped, blocks, vocab, mockann, book_idx)
    for rec in mapped:
        if rec.get('module') and rec['module'] in mod_map:
            rec['module_id'] = mod_map[rec['module']]['id']
            rec['module_name'] = mod_map[rec['module']]['name']
        else:
            rec['module_id'] = ''
            rec['module_name'] = ''
    # 用替换后的 mapped 重建 sample（保持顺序/总数）
    sample = [{k: v for k, v in x.items()
               if k in ('source_id', 'book', 'chunk_id', 'chunk_key', 'ordinal', 'page', 'part', 'text')}
              for x in mapped]
    SAMPLE.write_text(json.dumps({'seed': SEED, 'count': len(sample), 'replacements': replacements,
                                  'blocks': sample}, ensure_ascii=False, indent=1), encoding='utf-8')
    # 源 PDF
    pdf_dir = ROOT / 'corpus' / 'textbooks'
    pdfs = {p.name: p for p in pdf_dir.glob('*.pdf')}
    for rec in mapped:
        book = rec['book']
        match = next((p for n, p in pdfs.items() if book in n or n.rsplit('.', 1)[0] in book), None)
        rec['source_pdf'] = str(match) if match else str(pdf_dir)
    MAPPED.write_text(json.dumps({'seed': SEED, 'count': len(mapped), 'items': mapped},
                                 ensure_ascii=False, indent=1), encoding='utf-8')
    lines = []
    for i, x in enumerate(mapped, 1):
        lines.append(f"{i:03d}|{x['block_id']}|{x['book']}|p{x['page']}-{x['part']}|{x['block_type']}|"
                     f"{x['kp_primary']}|{','.join(x['kp_secondary'])}|{x['confidence']}|{x['status']}|{x['reason'][:160]}")
    BATCH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    # 报告
    non = sum(1 for x in mapped if x['status'] == 'non_content')
    gap = sum(1 for x in mapped if x['status'] == 'vocab_gap')
    mapped_n = sum(1 for x in mapped if x['status'] == 'mapped')
    low = sum(1 for x in mapped if x['status'] == 'mapped' and x['confidence'] <= 0.70)
    by_book = collections.Counter(x['book'] for x in mapped)
    by_type = collections.Counter(x['block_type'] for x in mapped)
    by_module = collections.Counter(x['module'] for x in mapped if x['module'])
    L = ['---', 'type: report', 'title: 教材块映射 100 块 pilot 报告', 'updated: 2026-11-06',
         'status: pilot', '---', '',
         '# 教材块映射 100 块 pilot 报告', '',
         '> 数据：PG textbook 1797 chunks（5 册）；只读，不写 PG/vault、不调 OCR。',
         '> 抽样：每册 20 块，页跨度均匀，seed=20261106，含少量封面/目录等非内容块。', '',
         '## 1. 样本与覆盖', '',
         '| 指标 | 数值 |', '| --- | --- |',
         f'| 抽样块数 | {len(mapped)}（5 册 ×20） |',
         f'| 内容块 primary 映射 | **{mapped_n}** |',
         f'| non_content（封面/目录/纯页码/前言/版权） | **{non}** |',
         f'| vocab_gap（内容块但词表无合适项） | **{gap}** |',
         f'| 低置信（≤0.70） | **{low}** |',
         f'| primary 覆盖率（内容块） | **{mapped_n}/{len(mapped)-non} = {mapped_n/max(1,len(mapped)-non)*100:.1f}%** |', '',
         '### 按册分布', '', '| 册 | 块数 |', '| --- | --- |']
    for b, n in by_book.items():
        L.append(f'| {b} | {n} |')
    L += ['', '### 块类型分布', '', '| 块类型 | 数量 |', '| --- | --- |']
    for t, n in by_type.most_common():
        L.append(f'| {t} | {n} |')
    L += ['', '### 候选模块分布', '', '| 模块 | 数量 |', '| --- | --- |']
    for m, n in by_module.most_common():
        L.append(f'| kp_{m} | {n} |')
    # 替换记录
    # Top10 歧义/不可映射
    bad = [x for x in mapped if x['status'] == 'vocab_gap']
    bad += [x for x in mapped if x['status'] == 'mapped' and x['confidence'] <= 0.70]
    bad = sorted(bad, key=lambda x: (x['status'] != 'vocab_gap', x['confidence']))[:10]
    if replacements:
        L += ['', '## 2. 空文本/指定块替换记录', '',
              '| 原 block_id | 原册/页 | 原类型 | 替换 block_id | 新册/页 | 新类型 | 理由 |',
              '| --- | --- | --- | --- | --- | --- | --- |']
        for r in replacements:
            L.append(f'| `{r["old_block_id"]}` | {r["old_book"][-8:]}/p{r["old_page"]} | {r["old_type"]} | '
                     f'`{r["new_block_id"]}` | {r["new_book"][-8:]}/p{r["new_page"]} | {r["new_type"]} | {r["reason"]} |')
        L += ['', '> 说明：这两块在 PG 原文非空、但文本以 `=` 开头，Excel 会把单元格当公式显示为空白；'
              '已同时修复 xlsx 全部文本单元格的公式转义，并按要求替换为同册近页内容块。', '']
    L += ['', '## 3. Top 10 歧义/不可映射块', '',
          '| block_id | 册/页 | 类型 | 状态 | 模型/原因 |', '| --- | --- | --- | --- | --- |']
    for x in bad:
        L.append(f'| `{x["block_id"]}` | {x["book"][-8:]}/p{x["page"]} | {x["block_type"]} | '
                 f'{x["status"]} | {x["kp_primary"] or "—"}；{x["reason"][:70]} |')
    L += ['', '## 4. 可行性判断', '',
          '1. **能否直接全量 1797？** 不建议直接全量。教材块是 OCR 的页/part 碎片，**没有 chapter/section 结构**，'
          '同一页块常混排章节导引、例题、习题与跨节内容；本 pilot 中 primary 虽多数可给，但低置信与 vocab_gap 集中在'
          '“章末复习/多节混排/前言导引”。',
          '2. **是否必须先补章节结构？** **建议先补**：至少为每块补 chapter/section（可从 PDF 目录/TOC 或'
          '教材页眉推断），再进行块级映射；否则全量产生的 primary 会在“整章复习/多节混排块”上系统性偏移。',
          '3. **词表是否需增补？** 需少量增补或明确规则：教材特有的“数学建模/阅读与思考/探究/信息技术应用”'
          '以及部分章导引内容，120 词表无对应；建议增加“教材栏目/非考点”规则或补充少量 kp。',
          '4. **一句话结论**：**先补章节结构（可半自动）+ 明确非内容/栏目规则，再做全量 1797**；'
          '直接对 1797 全量映射的边际质量不足。', '',
          f'- 产物：`blocks_1797.json`、`sample_100.json`、`mapped_100.json`、`mapped_100_batch.txt`、'
          f'`{XLSX.name}`（教师核对表）。', '']
    REPORT.write_text('\n'.join(L), encoding='utf-8')
    print(f'[prepare] blocks {len(blocks)}；sample {len(mapped)}；mapped {mapped_n}；non_content {non}；'
          f'vocab_gap {gap}；low {low}')
    print(f'输出：{MAPPED}\n报告：{REPORT}')
    return 0


def stage_xlsx(args):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter
    data = json.loads(MAPPED.read_text(encoding='utf-8'))
    items = data['items']
    vocab_md = VOCAB_MD
    # 模块与 120 词表（用于下拉）
    modules = []
    kps = []
    for line in vocab_md.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^##\s*\d+\.\s*(.+)`(kp_\d{2}_[a-z_]+)`', line)
        if m:
            modules.append(f'{m.group(2)}|{re.split(r"（", m.group(1))[0].strip()}')
        if line.strip().startswith('|'):
            parts = [x.strip() for x in line.strip().strip('|').split('|')]
            if len(parts) >= 3 and re.fullmatch(r'kp_\d{2}_\d{2}_[a-z0-9_]+', parts[0].strip('`')):
                kps.append(f'{parts[0].strip("`")}|{parts[1]}')
    wb = Workbook()
    ws = wb.active
    ws.title = '抽检100块'
    headers = ['序号', 'block_id', '册', '页码', 'part', '块类型', '完整原文', '模型模块',
               '模型primary', '名称', '模型secondary', '置信', '理由', '教师模块', '教师考点', '教师备注', '来源PDF']
    ws.append(headers)
    for i, x in enumerate(items, 1):
        ws.append([i, x['block_id'], x['book'], x['page'], x['part'], x['block_type'], None,
                   x['module_id'], x['kp_primary'], x['kp_name'],
                   ' '.join(x['kp_secondary']), x['confidence'], x['reason'],
                   '', '', '', x['source_pdf']])
        # 完整原文强制按字符串写入，避免以 = 开头被 Excel 当公式显示为空
        cell = ws.cell(row=ws.max_row, column=7)
        cell.value = x['text']
        cell.data_type = 's'
    # 词表 sheet 用于下拉
    ws2 = wb.create_sheet('词表')
    ws2['A1'] = '模块ID'; ws2['B1'] = '模块名称'
    ws2['C1'] = '考点ID'; ws2['D1'] = '考点名称'
    for i, m in enumerate(modules, 2):
        a, b = m.split('|', 1); ws2.cell(i, 1, a); ws2.cell(i, 2, b)
    for i, k in enumerate(kps, 2):
        a, b = k.split('|', 1); ws2.cell(i, 3, a); ws2.cell(i, 4, b)
    nrow = max(len(items) + 1, 2)
    dv_mod = DataValidation(type='list', formula1=f'=词表!$A$2:$A${len(modules)+1}', allow_blank=True)
    dv_kp = DataValidation(type='list', formula1=f'=词表!$C$2:$C${len(kps)+1}', allow_blank=True)
    ws.add_data_validation(dv_mod); ws.add_data_validation(dv_kp)
    dv_mod.add(f'N2:N{nrow}'); dv_kp.add(f'O2:O{nrow}')
    # 样式
    head_fill = PatternFill('solid', fgColor='DDEBF7')
    thin = Side(style='thin', color='BBBBBB'); border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c in ws[1]:
        c.fill = head_fill; c.font = Font(bold=True)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True); c.border = border
    widths = [6, 24, 34, 6, 6, 12, 90, 9, 22, 20, 24, 8, 50, 16, 22, 24, 52]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=True); c.border = border
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 70
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:Q{ws.max_row}'
    # 说明 sheet
    ws3 = wb.create_sheet('说明')
    lines = [
        ['教材块映射 pilot · 100 块教师核对表'],
        [''],
        ['目的', '验证“教材块 → 120 词表考点”的可行性；本表仅提供模型候选，教师模块/考点/备注待填。'],
        ['为什么没有 chapter', '当前 PG textbook chunk 的 locator 只有 page/part，没有 chapter/section；'
                              '块是 OCR 页/part 碎片，可能跨节混排，所以模型模块/primary 只是候选。'],
        ['怎么填', '教师模块、教师考点用下拉选择；认同可照抄候选，不同意请选正确项；备注写“错/部分对/原因”。'],
        ['non_content 规则', '封面/版权/目录/纯页码/前言/导引等非知识内容：模型 primary 留空，状态 non_content。'],
        ['vocab_gap 规则', '内容块但 120 词表无合适考点：模型 primary 留空，状态 vocab_gap，不硬塞。'],
        ['完整原文', '“完整原文”列保存 PG 原文，未截断；合并/超长单元格请用编辑栏查看。'],
        ['抽样', '5 册 ×20 块，册内按页跨度均匀，seed=20261106；含少量封面/目录用于检验 non_content。'],
    ]
    for r in lines:
        ws3.append(r)
    ws3['A1'].font = Font(bold=True, size=14)
    ws3.column_dimensions['A'].width = 22
    ws3.column_dimensions['B'].width = 110
    wb.save(XLSX)
    copy_to = getattr(args, 'xlsx_copy', None)
    if copy_to:
        import shutil
        target = pathlib.Path(copy_to)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(XLSX, target)
        print(f'[xlsx] {XLSX}（{len(items)} 行）；副本 {target}')
    else:
        print(f'[xlsx] {XLSX}（{len(items)} 行）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='教材块映射 100 块 pilot')
    ap.add_argument('--stage', choices=['prepare', 'xlsx'], default='prepare')
    ap.add_argument('--xlsx-copy', default=os.environ.get('CHILON_XLSX_COPY'),
                    help='可选：把生成的教师核对 xlsx 复制到该路径（默认不复制）')
    args = ap.parse_args(argv)
    if args.stage == 'prepare':
        return stage_prepare(args)
    return stage_xlsx(args)


if __name__ == '__main__':
    sys.exit(main())
