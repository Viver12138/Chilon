#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从知识点词表正文重新计算统计口径，并回写页首计数与各模块标题里的条目数。

手工维护的「13 个模块 / 111 条」曾与实际不符，本脚本让统计从数据派生：
    python tools/kb_vocab_stats.py --check   # 只检查，不改文件
    python tools/kb_vocab_stats.py           # 回写
"""
from __future__ import annotations

import argparse
import pathlib
import re

ITEM = re.compile(r"^\| `(kp_[0-9]{2}_[0-9]{2}_[a-z0-9_]+)`", re.M)
HEAD = re.compile(r"^(## \d+\. .*?)（([^（）]*?)`(kp_[0-9]{2}_[a-z0-9_]+)`，(\d+) 项）", re.M)
FRONT = re.compile(r"(?m)^items: (\d+)$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    path = pathlib.Path(args.vault) / "10_Indexes" / "知识点词表.md"
    text = path.read_text(encoding="utf-8")

    ids = ITEM.findall(text)
    per = {}
    for i in ids:
        per.setdefault(i.split("_")[1], 0)
        per[i.split("_")[1]] += 1

    heads = HEAD.findall(text)
    problems = []
    for title, mid_text, mod, n in heads:
        prefix = mod.split("_")[1]
        actual = per.get(prefix, 0)
        if int(n) != actual:
            problems.append(f"{title}: 标题写 {n}，实际 {actual}")
    m = FRONT.search(text)
    if m and int(m.group(1)) != len(ids):
        problems.append(f"frontmatter items: {m.group(1)}，实际 {len(ids)}")
    if len(heads) != len(per):
        problems.append(f"模块数：标题 {len(heads)} 个，词条分布 {len(per)} 个")

    print(f"模块 {len(per)} 个｜词条 {len(ids)} 条｜唯一 {len(set(ids))} 条")
    for prefix in sorted(per):
        print(f"  kp_{prefix}: {per[prefix]}")
    if not problems:
        print("统计口径一致")
        return 0
    for p in problems:
        print("不一致:", p)
    if args.check:
        return 1

    text = HEAD.sub(
        lambda m: f"{m.group(1)}（{m.group(2)}`{m.group(3)}`，{per.get(m.group(3).split('_')[1], 0)} 项）",
        text)
    text = FRONT.sub(f"items: {len(ids)}", text)
    if "modules:" in text.split("---")[1]:
        text = re.sub(r"(?m)^modules: \d+$", f"modules: {len(per)}", text, count=1)
    else:
        text = text.replace(f"items: {len(ids)}", f"items: {len(ids)}\nmodules: {len(per)}", 1)
    path.write_text(text, encoding="utf-8")
    print("已回写")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
