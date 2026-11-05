#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 04_Exams 下的 Document 笔记重新生成 10_Indexes/真题总览.md。

只读 Markdown frontmatter 与目录内题卡数量，不推断缺失字段。
"""
from __future__ import annotations

import pathlib
import re
import sys

VAULT = pathlib.Path(r'C:\Users\Viver\Desktop\高中数学')


def parse_frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        return {}
    end = text.find('\n---\n', 3)
    if end < 0:
        return {}
    out = {}
    for line in text[4:end].splitlines():
        if ':' not in line or line.startswith(' '):
            continue
        k, _, v = line.partition(':')
        out[k.strip()] = v.strip().strip('"')
    return out


def main() -> int:
    docs = []
    for p in sorted((VAULT / '04_Exams').rglob('*.md')):
        fm = parse_frontmatter(p)
        if fm.get('document_type') != 'gaokao':
            continue
        qcount = len(list(p.parent.glob('*-q*.md')))
        docs.append({
            'id': fm.get('document_id', ''),
            'title': fm.get('title', ''),
            'year': int(fm.get('year') or 0),
            'region': fm.get('region', ''),
            'kind': fm.get('paper_kind', ''),
            'status': fm.get('processing_status', ''),
            'note': p.stem,
            'qcount': qcount,
        })

    docs.sort(key=lambda d: (-d['year'], d['id']))
    years = sorted({d['year'] for d in docs}, reverse=True)

    lines = ['---', 'type: index', 'title: 真题总览', 'updated: 2026-11-05', 'generated: D:/Chilon/tools/kb_index.py', '---', '',
             '# 真题总览', '', '> 返回 [[首页]] ｜ 见 [[知识点总览]] ｜ 本页由 `D:/Chilon/tools/kb_index.py` 自动生成，勿手改', '']

    for y in years:
        ys = [d for d in docs if d['year'] == y]
        total_q = sum(d['qcount'] for d in ys)
        lines += [f'## {y}（{len(ys)} 份，{total_q} 题）', '',
                  '| document_id | 试卷 | 地区 | 科类 | 题数 | 状态 | 笔记 |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
        for d in ys:
            lines.append(f"| `{d['id']}` | {d['title']} | {d['region']} | {d['kind'] or '—'} | "
                         f"{d['qcount']} | {d['status']} | [[{d['note']}]] |")
        lines.append('')

    lines += ['## 归档口径', '',
              '- 一份试卷 = `04_Exams/Gaokao/<year>/<地区>-<科类>/` 下一个 Document 笔记',
              '- 原卷只存在于 `01_Raw/Gaokao/<year>/<地区>-<科类>/`',
              '- 每道题拆成独立 Question 笔记，命名 `<试卷名>-q<题号>`',
              '- 解析版与原卷同名加后缀 `-解析版`', '',
              '## 数据来源', '',
              '- 2012 年起的高考真题取自 `DxAThing/Gaokao-Math-Problems-Compilation`（LaTeX 源，CC BY-SA 4.0）',
              '- 由 `tools/tex2kb.py` 机转，未经人工逐题核对，`processing_status` 为 `needs_review`', '']

    (VAULT / '10_Indexes' / '真题总览.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'papers={len(docs)} years={len(years)} questions={sum(d["qcount"] for d in docs)}')
    for y in years:
        ys = [d for d in docs if d['year'] == y]
        print(f'  {y}: {len(ys)} 份 / {sum(d["qcount"] for d in ys)} 题')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


