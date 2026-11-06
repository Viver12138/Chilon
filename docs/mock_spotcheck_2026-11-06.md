---
type: report
title: 93 题模拟题标注教师抽检与修正（摘要，2026-11-06）
updated: 2026-11-06
---

# 93 题模拟题标注教师抽检与修正（摘要）

> 来源：用户提供的教师填写件 `模拟题标注抽检_93题_2026-11-06_完整版.txt`（sha256 `4e107f61a5dec259…`）。
> 样本：93 题（按 primary 模块分层，seed=20261106，含低置信与空 primary 样本）。
> 本记录按填写件执行修正，未独立核实填写人身份；**93 题是抽样，不代表其余 838 题**。

## 1. 一致率（修正前基线）

| 指标 | 结果 |
| --- | --- |
| 模块一致 | **76/93 = 81.7%** |
| 考点 exact | **51/93 = 54.8%** |
| primary+secondary 命中 | **55/93 = 59.1%** |
| 考点不一致 | **42/93** |
| 用户自评 vs 计算口径差异 | 14 条（不改判定，仅说明口径） |

- 模块按 120 词表 `kp_XX` 前缀算，考点按 exact 算；含 secondary 属于宽松口径。
- 14 条差异主要是用户把“同模块、考点偏”单列，或按更细的二级模块判“模块不一致”；计算口径沿用 `kp_XX` 前缀。

## 2. 修正结果

- 93 题：primary = 教师考点，secondary 清空，`classification_source=teacher`、`confidence=1.0`、`model_version=spotcheck-2026-11-06`。
- PG：mock primary 931 行不变（**teacher 93 + model 838**）；primary 非空 **912**、空 **19**（21 减去样本内补齐的 2 条）。
- secondary：230 → **209**。
- 高考 annotations **8007**、legacy **793** 不变；备份 / 幂等 / 回滚实测。

## 3. 卡片与索引

- 重投影写入 **43** 个文件；931 卡 + 67 set note 数量不变；93 张教师修正卡的 kp 恰为教师考点（**93/93**）。
- 空 primary 卡 19 张；高考卡 6324 张聚合 sha256 未变。
- 未调 OCR；未做 Qdrant（标注不改 chunk 文本，15 条 no-rerank 基线仍 93.3%）。

## 4. 剩余风险

- **838 题仍是模型标注**，未抽检；93 题只代表样本，不是全库准确率。
- 19 条空 primary 建议后续人工补。
- 整体 `annotation.status` 仍为 **needs_review**，不批量升级。

> 明细：`var/mock_annotations/full/spotcheck_result.md`（修正前一致率 / 42 题清单 / 14 条口径差异）、`spotcheck_apply_report.md`（PG apply 计数）。`var/` 不提交。
