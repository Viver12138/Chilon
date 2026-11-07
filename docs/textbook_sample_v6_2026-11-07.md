---
type: report
title: 教材 v6 复核表（剩余 839 块抽 20%）
updated: 2026-11-07
status: sample-pending-review
---

# 教材 v6 复核表（剩余 839 块抽 20%）

> 目标：第四批复核——剩余 model 块的 20% 抽样（pilot 100 已在第三批补齐，本轮不再回采）。
> 基于 v6 映射（`mapped_1797_reviewed_v6.json`）；未写 PG/vault、未调 OCR。

## 1. 口径

- model 池 **839**（teacher 958 已排除）；
- 20% = **168** 块（839 × 20% 向上取整）；seed=20261107；
- model 池当前全部为 `mapped`（vocab_gap/non_content 已在第三批被教师处理完，模型池无稀有状态）；
- 与 teacher 958 零重叠。

## 2. 按册

| 册 | 样本 |
| --- | ---: |
| 必修第一册 | 57 |
| 必修第二册 | 48 |
| 选择性必修第一册 | 23 |
| 选择性必修第二册 | 15 |
| 选择性必修第三册 | 25 |
| **合计** | **168** |

## 3. 表格

文件：`review_sheets/samples/教材映射复核_v6_剩余839块_20pct_2026-11-07.xlsx`（168 行）

- 列：`序号/来源/block_id/册/章/节/页码/块类型/完整原文/模型模块/模型primary/名称/模型secondary/置信/理由/v6规则/v5模型primary/教师模块/教师考点/备注/来源PDF`；
- `来源` 列本轮全为 `20%抽样`（保留列结构便于跨批对比）；
- 模型列是 v6 候选；`v6规则` 为修正层来源，`v5模型primary` 供对比；
- 待填：教师模块（R）、教师考点（S）、备注（T）；前两列 17/120 下拉；
- 排序：册 → 页码 → part → ordinal；冻结首行 + 自动筛选；说明 sheet 含口径。

## 4. 校验（已实测）

- 168 行、block_id **168 唯一**，与 sample json 一致；
- 与 teacher 958 **零重叠**；全部 `review_status=model`；
- 教师列留空、完整原文非空、按册页排序、17/120 下拉 `R2:R169` / `S2:S169`。

## 5. 回填

填完放回 `review_sheets/filled/`（文件名不变），再解析：
与 teacher 958 合并 → reviewed/PG → 重投影 Obsidian 块级链接。
若全部填完，teacher 将达 **1126/1797 = 62.7%**。

## 6. 边界

- 20% 抽样是抽样，不是全量；准确率仍按样本报告，不能外推全量；
- 抽完还剩 **671** 个 model 块；需再一轮终检后才谈 model 标签转正式；
- v6 的 8 条规则修正见 `docs/textbook_map_v6_2026-11-07.md`。

---

> 工具：`tools/kb_textbook_sample_v5_combined.py`（`--reviewed/--mapped/--rule-label/--prev-label` 可复用）；
> 抽样数据：`var/textbook_mapping/sample_review_v6_20pct_2026-11-07.json`（不提交）。
