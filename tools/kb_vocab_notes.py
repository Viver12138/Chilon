#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 10_Indexes/知识点词表.md 生成 level-3 知识点笔记骨架。

     python tools/kb_vocab_notes.py            # 生成缺失的笔记
     python tools/kb_vocab_notes.py --check    # 只报告缺哪些

不覆盖已存在的文件：已有笔记可能是人工写过的。
"""
from __future__ import annotations

import argparse
import pathlib
import re

ROW = re.compile(r"^\| `(kp_([0-9]{2})_[0-9]{2}_[a-z0-9_]+)` \| ([^|]+?) \| (.*) \|\s*$", re.M)

MODULE_META = {
    "01": ("集合与常用逻辑用语", "人教A版", "必修第一册 第一章 集合与常用逻辑用语"),
    "02": ("函数", "人教A版", "必修第一册 第三、四章"),
    "03": ("导数", "人教A版", "选择性必修第二册 第五章 一元函数的导数及其应用"),
    "04": ("三角函数", "人教A版", "必修第一册 第五章 三角函数"),
    "05": ("平面向量", "人教A版", "必修第二册 第六章 平面向量及其应用"),
    "06": ("复数", "人教A版", "必修第二册 第七章 复数"),
    "07": ("数列", "人教A版", "选择性必修第二册 第四章 数列"),
    "08": ("立体几何", "人教A版", "必修第二册 第八章；选择性必修第一册 第一章"),
    "09": ("解析几何", "人教A版", "选择性必修第一册 第二、三章"),
    "10": ("统计与概率", "人教A版", "必修第二册 第九、十章；选择性必修第三册 第七、八章"),
    "11": ("统计与概率", "人教A版", "选择性必修第三册 第六章 计数原理"),
    "12": ("函数", "人教A版", "必修第一册 第二章 一元二次函数、方程和不等式"),
    "14": ("算法初步", "旧课标", "旧课标必修三 第一章（新教材已删除）"),
    "15": ("平面几何选讲", "旧课标", "旧课标选修 4-1 几何证明选讲（新教材已删除）"),
}

MODULE_ID = {
    "01": "kp_01_set_logic", "02": "kp_02_function", "03": "kp_03_derivative",
    "04": "kp_04_trig", "05": "kp_05_vector", "06": "kp_06_complex",
    "07": "kp_07_sequence", "08": "kp_08_solid", "09": "kp_09_analytic",
    "10": "kp_10_prob_stat", "11": "kp_11_counting", "12": "kp_12_inequality",
    "14": "kp_14_algorithm",
    "15": "kp_15_plane_geometry",
}

LEGACY = {
    "kp_08_01_threeview", "kp_12_04_region", "kp_09_13_polar", "kp_09_14_param_eq",
    "kp_12_09_abs_inequality", "kp_12_10_cauchy", "kp_14_01_flowchart",
    "kp_15_01_similar_triangle", "kp_15_02_circle_power",
}
NEW_BOOK = {"kp_10_12_normal"}

TEMPLATE = """---
kp_id: {kp_id}
name: "{name}"
parent: {module_id}
level: 3
tree_node: {tree_node}
textbook: {textbook}
chapter: "{chapter}"
tags: []
era: {era}
status: draft
---

# {name}

> 返回 [[知识点总览]] ｜ 所属模块 [[{module_id}]] ｜ 词表 [[知识点词表]]

## 定义

{definition}

## 教材位置

- {textbook}：{chapter}
- 时代：{era}

## 典型例题

> 待补。pilot 阶段每词条至少挂 1 道真题：`question_id` + 为什么是它。

## 反例

> 待补。**没有反例的标签不能用于标注**——十个人会标出十个意思。

## 关联题目

> 待补。格式 `[[2012安徽理-q05]]`（question_id 与卡片名对应）。

## 备注

- 由 `tools/kb_vocab_notes.py` 依词表生成，`status: draft`
- 定义取自词表，改写定义需同步词表，避免两处不一致
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    vault = pathlib.Path(args.vault)
    vocab = (vault / "10_Indexes" / "知识点词表.md").read_text(encoding="utf-8")
    rows = [(m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip())
            for m in ROW.finditer(vocab)]
    if not rows:
        print("未解析到词条，检查词表表格格式")
        return 2

    made = skipped = 0
    missing = []
    for kp_id, prefix, name, definition in rows:
        tree_node, textbook, chapter = MODULE_META[prefix]
        folder = vault / "05_KnowledgePoints" / tree_node
        path = folder / f"{kp_id}.md"
        if path.exists():
            skipped += 1
            continue
        missing.append(kp_id)
        if args.check:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        era = "旧课标" if kp_id in LEGACY else ("新教材" if kp_id in NEW_BOOK else "通用")
        path.write_text(TEMPLATE.format(
            kp_id=kp_id, name=name, module_id=MODULE_ID[prefix], tree_node=tree_node,
            textbook=textbook, chapter=chapter, definition=definition, era=era,
        ), encoding="utf-8")
        made += 1

    print(f"词表 {len(rows)} 条｜生成 {made}｜已存在跳过 {skipped}｜待生成 {len(missing)}")
    if args.check and missing:
        for i in missing:
            print("  缺:", i)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
