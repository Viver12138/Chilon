#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 level-3 知识点笔记回填「典型例题」候选与「反例」分界。

    python tools/kb_vocab_examples.py            # 回填
    python tools/kb_vocab_examples.py --check    # 只报告覆盖情况

检索词与反例来自 tools/kb_vocab_examples_data.py；例题按题干关键词打分，
优先命中词多、题干短、年份较早的题；全库不重复使用同一道题。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from kb_vocab_examples_data import DATA  # noqa: E402


def load_rows() -> list[tuple[str, list[str], str]]:
    rows = []
    for line in DATA.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kp, kw, nots = line.split("|", 2)
        rows.append((kp.strip(), [k for k in kw.strip().split() if k], nots.strip()))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    vault = pathlib.Path(args.vault)
    rows = load_rows()

    # 试卷目录 / 题卡名
    doc_map = {}
    for d in (vault / "04_Exams").rglob("*.md"):
        if "-q" in d.name:
            continue
        head = d.read_text(encoding="utf-8")[:800]
        m = re.search(r"(?m)^document_id:\s*(\S+)", head)
        if m:
            doc_map[m.group(1)] = (d.parent, d.stem)

    questions = []
    for j in (vault / "02_Processed" / "OCR_JSON").rglob("questions.json"):
        b = json.loads(j.read_text(encoding="utf-8"))
        doc_id = b["document_id"]
        if doc_id not in doc_map:
            continue
        folder, label = doc_map[doc_id]
        year = int(doc_id.split("_")[1])
        for q in b["questions"]:
            n = q["question_number"]
            questions.append({
                "qid": q["question_id"], "stem": q["stem"], "year": year,
                "label": f"{label}-q{int(n):02d}", "paper": label, "num": int(n),
                "type": q["question_type"],
            })

    used = set()
    filled = empty = 0
    for kp_id, kws, nots in rows:
        # 打分：命中词数优先，其次题干短，其次年份早
        cands = []
        for q in questions:
            hits = [k for k in kws if k in q["stem"]]
            if not hits:
                continue
            cands.append((len(hits), -len(q["stem"]), -q["year"], q, hits))
        cands.sort(key=lambda x: (-x[0], -x[1], -x[2]))
        pick = None
        for c in cands:
            if c[3]["qid"] not in used:
                pick = c
                break
        if pick:
            used.add(pick[3]["qid"])

        notes = list((vault / "05_KnowledgePoints").rglob(f"{kp_id}.md"))
        if not notes:
            continue
        note = notes[0]
        text = note.read_text(encoding="utf-8")

        if pick:
            hits = "、".join(pick[4])
            example = (f"- [[{pick[3]['label']}]] — {pick[3]['paper']} 第 {pick[3]['num']} 题"
                       f"（匹配：{hits}）\n\n"
                       "> 候选例题：按题干关键词自动匹配，**待人工确认**是否确为该词条的典型代表。\n")
            filled += 1
        else:
            example = "> 未匹配到合适真题，待人工补一道。\n"
            empty += 1
        nots_text = f"{nots}\n"

        text = re.sub(r"(?s)(## 典型例题\n\n).*?(?=\n## )", lambda m: m.group(1) + example, text, count=1)
        text = re.sub(r"(?s)(## 反例\n\n).*?(?=\n## )", lambda m: m.group(1) + nots_text, text, count=1)
        if not args.check:
            note.write_text(text, encoding="utf-8")

    print(f"词条 {len(rows)}｜有候选例题 {filled}｜无匹配 {empty}｜去重后使用 {len(used)} 道题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
