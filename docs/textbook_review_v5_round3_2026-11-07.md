---
type: report
title: 教材第三批组合复核结果（310 块：20% + pilot100）
updated: 2026-11-07
status: review-round3
---

# 教材第三批组合复核结果（310 块）

> 输入：`review_sheets/filled/复核_v5.txt`（5 列含 block_id）；v5 映射为候选；
> 教师标签 → reviewed/PG/Obsidian 链接；不调 OCR。

## 1. 解析与口径

- 解析 **310/310**，block_id 与组合样本一致；模块/考点合法且同模块；
- 教师完整标签 **273**、只有模块无考点 **9**、留空 **28**；
- 留空 → non_content（其中模型原判内容 18 条）；
- 只有模块无考点 → vocab_gap（保留模块，表示“词表缺合适考点/不宜硬塞”）。

## 2. v5 在第三批上的准确率

| 口径 | 分母 | 模块 | exact |
| --- | ---: | ---: | ---: |
| 完整标签（module+exact） | 273 | 270 = 98.9% | 265 = 97.1% |
| 含 module_only（exact 记 0） | 282 | 278 = 98.6% | 265 = 94.0% |

### 分来源

| 来源 | 完整标签 | 模块 | exact |
| --- | ---: | ---: | ---: |
| 20% 抽样 | 192 | 191 = 99.5% | 186 = 96.9% |
| pilot100 回采 | 81 | 79 = 97.5% | 79 = 97.5% |
| **合计** | **273** | **270 = 98.9%** | **265 = 97.1%** |

### 不一致清单（v5 错、教师对，8 条，供 v6 规则）

| block_id | 教师 | v5 | 来源 | 备注 |
| --- | --- | --- | --- | --- |
| `TB-B1-0101-1-p0101-01` | `kp_02_13_segment` | `kp_02_01_concept` | 20%抽样 | 需改：分段函数应用 |
| `TB-B1-0155-2-p0155-02` | `kp_02_12_abstract` | `kp_02_09_logarithm` | 20%抽样 | 需改：函数模型应用 |
| `TB-B1-0162-1-p0162-01` | `kp_02_11_zero` | `kp_02_12_abstract` | 20%抽样 | 需改：零点与二分法 |
| `TB-B1-0254-2-p0254-02` | `kp_04_11_apply` | `（空）` | pilot100 | 需改：补三角函数应用 |
| `TB-B2-0061-3-p0061-03` | `kp_04_09_cosine` | `kp_05_01_concept` | pilot100 | 需改：解三角形，非向量概念 |
| `TB-B2-0068-1-p0068-01` | `kp_04_09_cosine` | `kp_05_01_concept` | 20%抽样 | 需改：解三角形 |
| `TB-B2-0154-1-p0154-01` | `kp_08_06_angle` | `kp_08_03_position` | 20%抽样 | 需改：异面直线所成角/垂直 |
| `TB-B5-0064-1-p0064-01` | `kp_03_08_concept` | `kp_03_03_monotonic` | 20%抽样 | 需改：导数概念/变化率 |

## 3. reviewed 更新

- `mapped_1797_reviewed_round3.json`：teacher **958** / model **839**；
- 本轮新增 teacher **310** 条（上批 648 不动）；status {'non_content': 74, 'mapped': 1714, 'vocab_gap': 9}。

## 4. 入库与 Obsidian 重投影

- PG `textbook_block_annotations` active **1797**：teacher **958** / model **839**；
  status mapped **1714** / non_content **74** / vocab_gap **9**；`knowledge_annotations` **9092** 未变；幂等重跑 **0 变更**；
- 版本：model 行 `textbook-map-v5-2026-11-07`（839）；teacher 行按批保留
  `2026-11-06`（360）/ `v4-round2`（288）/ `v5-round3`（310）；
- vault 5 册重投影：**1714 条知识点链接**（teacher 875 + model 839）+ **9 条待补**；
  删链接行与写前投影 **0 差异**、目标 missing **0**、二次 dry-run **0 变更**；高考卡 6324 张 sha256 未变；
- 已复核占比 **958/1797 = 53.3%**，model 剩余 **839**。

## 5. 边界

- 20% 抽样 + pilot 全量回采都是抽样/回采，不是全量；准确率仍是样本值；
- module_only 9 条按“有模块、无合适主考点”记 vocab_gap（PG status=vocab_gap、module 保留），不强行塞考点；
- 8 条不一致留待 v6 规则收敛；pilot 100 的历史欠账已补；
- 剩余 839 model 块仍需后续抽检，model 标签未转正式。

---

> 明细：`review_round3_parsed.json`。
