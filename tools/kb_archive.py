#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 corpus 的原卷 PDF 归档进知识库 01_Raw，并回填 Document 的 source_file/page_count/hash。

用法：
    python tools/kb_archive.py --years 2012-2026
    python tools/kb_archive.py --vault "C:/Users/Viver/Desktop/高中数学"

匹配规则：文件名去掉括号区县说明后与「年份+地区+科类」比对；
全国 I/II/III 与 corpus 的阿拉伯数字 1/2/3 视为同一卷；2024 语料只写「全国」。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil

try:  # pypdf 可选：缺库时 page_count 记为 null
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

KIND = {"理科": "理", "文科": "文", "春季": "春"}


def norm(s: str) -> str:
    s = s.replace("Ⅰ", "1").replace("Ⅱ", "2").replace("Ⅲ", "3")
    s = s.replace("III", "3").replace("II", "2").replace("I", "1")
    return s


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--corpus", default=r"D:\Chilon\corpus\gaokao-papers")
    ap.add_argument("--years", default="")
    args = ap.parse_args()

    vault = pathlib.Path(args.vault)
    docs_root = vault / "04_Exams" / "Gaokao"
    raw_root = vault / "01_Raw" / "Gaokao"

    corpus = {}
    for p in pathlib.Path(args.corpus).glob("*.pdf"):
        corpus.setdefault(norm(p.stem.split("(")[0]), p)

    wanted = None
    if args.years:
        lo, _, hi = args.years.partition("-")
        wanted = range(int(lo), int(hi or lo) + 1)

    total = patched = 0
    missing = []
    for year_dir in sorted(d for d in docs_root.iterdir() if d.is_dir() and d.name.isdigit()):
        if wanted is not None and int(year_dir.name) not in wanted:
            continue
        year = year_dir.name
        rows = []
        for folder in sorted(d for d in year_dir.iterdir() if d.is_dir()):
            parts = folder.name.split("-")
            region, kind = parts[0], (parts[1] if len(parts) > 1 else "")
            short = KIND.get(kind, "")
            label = f"{year}{region}{short}"
            cands = [norm(label)]
            if region in ("全国甲", "全国乙"):
                cands.append(norm(f"{year}全国{short}"))
            src = next((corpus[c] for c in cands if c in corpus), None)
            if src is None:
                missing.append((year, folder.name, label))
                continue

            out_dir = raw_root / year / folder.name
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / f"{label}.pdf"
            if not dest.exists():
                shutil.copy2(src, dest)

            pages = len(PdfReader(str(dest)).pages) if PdfReader else None
            h = sha256(dest)
            rows.append((label, folder.name, src.name, dest.stat().st_size, pages, h))
            total += 1

            md = folder / f"{label}.md"
            if not md.exists():
                continue
            text = md.read_text(encoding="utf-8")
            end = text.find("\n---\n", 3)
            fm, body = text[4:end], text[end + 5:]
            fields = [
                ("source_file", f"01_Raw/Gaokao/{year}/{folder.name}/{label}.pdf"),
                ("page_count", "null" if pages is None else str(pages)),
                ("content_hash", h),
            ]
            for key, val in fields:
                if re.search(rf"(?m)^{key}:", fm):
                    fm = re.sub(rf"(?m)^{key}:.*$", f"{key}: {val}", fm)
                else:
                    fm += f"\n{key}: {val}"
            md.write_text("---\n" + fm + "\n---\n" + body, encoding="utf-8")
            patched += 1

        if rows:
            lines = ["---", "type: manifest", f"title: {year} 原卷来源映射", "---", "",
                     f"# {year} 原卷来源映射", "",
                     "| 试卷 | 目录 | 上游文件 | 页数 | 大小 | SHA-256 |",
                     "| --- | --- | --- | --- | --- | --- |"]
            for r in rows:
                pages = "—" if r[4] is None else r[4]
                lines.append(f"| {r[0]} | `{r[1]}` | `{r[2]}` | {pages} | {r[3] // 1024} KB | `{r[5]}` |")
            lines += ["", "> 上游 PDF 与知识库条目同源：PDF 是 TeX 源编译产物，内容以 TeX 为准。", ""]
            (raw_root / year / "来源映射.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"{year}: {len(rows)} 份")

    print(f"\n归档 {total} 份｜回填 Document {patched}｜缺 PDF {len(missing)}")
    for m in missing:
        print("  缺:", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
