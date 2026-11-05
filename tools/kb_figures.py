#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把题目引用的图形从 LaTeX 仓库 img/ 复制进知识库 09_Assets，并接入题卡。

用法：
    python tools/kb_figures.py --repo D:/Chilon/var/_tex_clone/repo

依赖上一步产出的 02_Processed/OCR_JSON/<document_id>/questions.json（含 figures 路径）。
TikZ 重绘源（img_repaint/*.tex）无法直接当图片用，会被跳过并计入 missing。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--repo", default=r"D:\Chilon\var\_tex_clone\repo")
    args = ap.parse_args()

    vault = pathlib.Path(args.vault)
    repo = pathlib.Path(args.repo)
    assets = vault / "09_Assets"

    # document_id -> (目录, 试卷名)
    doc_map = {}
    for d in (vault / "04_Exams").rglob("*.md"):
        if "-q" in d.name:
            continue
        head = d.read_text(encoding="utf-8")[:800]
        m = re.search(r"(?m)^document_id:\s*(\S+)", head)
        if m:
            doc_map[m.group(1)] = (d.parent, d.stem)

    copied = missing = touched = 0
    for bundle_path in sorted((vault / "02_Processed" / "OCR_JSON").rglob("questions.json")):
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        doc_id = bundle["document_id"]
        figs = bundle.get("figures") or []
        if not figs or doc_id not in doc_map:
            continue
        folder, label = doc_map[doc_id]
        out_dir = assets / doc_id
        out_dir.mkdir(parents=True, exist_ok=True)

        by_q = {}
        for f in figs:
            if not f.get("figure_id"):
                continue
            src_path = f.get("path")
            if not src_path:
                by_q.setdefault(f.get("question_id"), []).append(f)
                continue
            src = repo / src_path
            if not src.exists():
                missing += 1
                continue
            dest = out_dir / f"{f['figure_id']}.png"
            if not dest.exists():
                shutil.copy2(src, dest)
                copied += 1
            f["image_path"] = f"09_Assets/{doc_id}/{f['figure_id']}.png"
            by_q.setdefault(f.get("question_id"), []).append(f)
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        for qid, fs in by_q.items():
            num = int(qid.rsplit("_q", 1)[-1])
            card = folder / f"{label}-q{num:02d}.md"
            if not card.exists():
                continue
            text = card.read_text(encoding="utf-8")
            embeds = "\n".join(f"![[{f['figure_id']}.png]]" for f in fs)
            section = f"## 图形\n\n{embeds}\n\n> 来源：上游 `img/`，见 `09_Assets/{doc_id}/`\n"
            if re.search(r"(?s)## (图形|图形引用)\n\n.*?(?=\n## )", text):
                text = re.sub(r"(?s)## (图形|图形引用)\n\n.*?(?=\n## )", section, text, count=1)
            else:
                text = text.replace("\n## 校核", f"\n{section}\n## 校核", 1)
            card.write_text(text, encoding="utf-8")
            touched += 1

    print(f"复制图片 {copied}｜缺源图 {missing}｜更新题卡 {touched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
