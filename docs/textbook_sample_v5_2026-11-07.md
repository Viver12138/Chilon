---
type: report
title: 教材 v5 组合复核表（剩余 20% + pilot 100）
updated: 2026-11-07
status: sample-pending-review
---

# 教材 v5 组合复核表（剩余 20% + pilot 100）

> 目标：第三批复核一次填完——剩余 model 块的 20% 抽样 + pilot 100 全量回采（补历史缺失的逐块教师标签）。
> 基于 v5 映射（`mapped_1797_reviewed_v5.json`）；未写 PG/vault、未调 OCR。

## 1. 口径

- model 池 **1149**（teacher 648 已排除）；
- 抽样池 = model − pilot 100 = **1049**；20% = **210** 块；
- pilot **100** 块全量回采（`sample_100.json` 对应块）；
- 合计 **310 行**；seed=20261107；抽样与 pilot 零重叠、与 teacher 648 零重叠。

## 2. 构成

| 来源 | 行数 | 风险构成 |
| --- | ---: | --- |
| 20% 抽样 | 210 | normal 174 / 低置信 36 |
| pilot100 回采 | 100 | normal 74 / 低置信 15 / non_content 10 / vocab_gap 1 |
| **合计** | **310** | mapped 299 / non_content 10 / vocab_gap 1 |

按册：必修第一册 **91**、必修第二册 **80**、选择性必修第一册 **49**、选择性必修第二册 **39**、选择性必修第三册 **51**。

## 3. 表格

文件：`review_sheets/samples/教材映射复核_v5_剩余20pct+pilot100_2026-11-07.xlsx`（310 行）

- 列：`序号/来源/block_id/册/章/节/页码/块类型/完整原文/模型模块/模型primary/名称/模型secondary/置信/理由/v5规则/v4模型primary/教师模块/教师考点/备注/来源PDF`；
- `来源` 列可筛选：`20%抽样` / `pilot100回采`；
- 模型列是 v5 候选；`v5规则` 为修正层来源，`v4模型primary` 供对比；
- **待填**：教师模块（R）、教师考点（S）、备注（T）；前两列为 17/120 下拉；
- 排序：册 → 页码 → part → ordinal；冻结首行 + 自动筛选。

## 4. 校验（已实测）

- 310 行、block_id **310 唯一**，与 sample json 一致；
- 与 teacher 648 **零重叠**；全部是当前 model 块；
- 教师列留空、完整原文非空、按册页排序、17/120 下拉范围 `R2:R311` / `S2:S311`；
- 说明 sheet 含口径与回填方式。

## 5. 回填

填完放回 `review_sheets/filled/`（文件名不变），再解析：与 teacher 648 合并 → reviewed/PG → 重投影 Obsidian 块级链接。
若全部填完，teacher 将达约 **958/1797 = 53%**（pilot 100 也补回）。

## 6. 边界

- 20% 抽样来自**非-pilot**剩余 1049，pilot 100 是**全量**而非抽样；
- 抽样按册/置信分层、章轮转，风险构成接近总体；但仍不是无偏全量样本，**不能直接外推全量准确率**；
- v5 规则只修了 5 条 harmed；剩余 36 条 288 子集不一致未处理，下一批回填后可继续收敛。

---

> 工具：`tools/kb_textbook_sample_v5_combined.py`（可 `--percent` / `--seed` 重跑）；
> 抽样数据：`var/textbook_mapping/sample_review_v5_20pct_pilot100_2026-11-07.json`（不提交）。
