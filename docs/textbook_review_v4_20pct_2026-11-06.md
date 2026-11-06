---
type: report
title: 教材 v4 20% 复核结果（288 块，2026-11-06）
updated: 2026-11-06
status: review-round2
---

# 教材 v4 20% 复核结果（288 块）

> 输入：`review_sheets/filled/教材映射复核_v4.txt`（4 列，无 block_id，按序号对应复核表 xlsx 排序）；
> 教师标签用于评估与 reviewed 更新；不调 OCR；PG 入库与 vault 链接重投影见 §5。

## 1. 解析与口径

- 回填表对应**默认 288 表**（剔除 pilot）：按序匹配 exact **229**，若按“含 pilot”序只有 **102** → 判定为默认表；
- 解析 **288/288**，序号 1–288 连续；模块/考点合法、同模块校验通过；
- 教师有标签 **271**，留空 **17**；
- 内容分母（教师有标签且 v4 模型非 non_content）= **270**。

## 2. 模型准确率（v4 在 288 块上的样本指标）

| 指标 | 命中 | 比例 |
| --- | ---: | ---: |
| 模块一致 | 262 | 97.0% |
| 考点 exact | 229 | 84.8% |
| 含 secondary | 229 | 84.8% |
| v3 对照 exact | 200 | 74.1% |

- v3→v4 同分母对照：修好 **34**、改坏 **5**（以教师标签为准）。

### 分层

| 层 | 分母 | exact | 比例 |
| --- | ---: | ---: | ---: |
| low_conf | 51 | 34 | 66.7% |
| normal | 219 | 195 | 89.0% |

## 3. 留空与 cross 情况

- 教师留空但模型判内容：**5** 条；
- 模型判 non_content 但教师给标签：**1** 条；
- 本轮按教师判定处理：留空 → non_content；有标签 → mapped。

## 4. reviewed 更新

- `mapped_1797_reviewed_round2.json`：teacher **648** / model **1149**；
- 本轮新增 teacher **288** 条；与已有 teacher 360 **零重叠**。

## 5. 入库与 Obsidian 重投影

- PG `textbook_block_annotations` active **1797**：teacher **648**（360 旧版 + 288 round2）/ model **1149**；
  status mapped **1740** / non_content **56** / vocab_gap **1**；`knowledge_annotations` **9092** 未变；幂等重跑 **0 变更**；
- 版本：model 行 `textbook-map-v4-2026-11-06`；teacher 行 360 + 288 分别为
  `textbook-review-2026-11-06` / `textbook-review-v4-round2-2026-11-06`；
- vault 5 册重投影：**1740 条知识点链接**（teacher 602 + model 1138）+ **1 条待补**；
  删链接行与写前投影 **0 差异**、链接目标 missing **0**、二次 dry-run **0 变更**。

## 6. 改坏清单（v3 对、v4 错，5 条，留待 v5 规则修正）

| block_id | 教师 | v3 | v4（错） | 备注 |
| --- | --- | --- | --- | --- |
| `TB-B1-0083-1-p0083-01` | kp_02_04_monotonic | 同教师 | kp_02_03_range | 3.2 节导语，v4 “最值”窄规则过粗 |
| `TB-B1-0086-1-p0086-01` | kp_02_04_monotonic | 同教师 | kp_02_03_range | 3.2 单调性证明例 3 |
| `TB-B1-0155-1-p0155-01` | kp_02_12_abstract | 同教师 | kp_02_08_exponential | 4.5.3 函数模型应用导语 |
| `TB-B1-0157-2-p0157-02` | kp_02_12_abstract | 同教师 | kp_02_08_exponential | 碳 14 半衰期模型（应用 vs 指数函数） |
| `TB-B1-0157-3-p0157-03` | kp_02_12_abstract | 同教师 | kp_02_08_exponential | 马尔萨斯人口模型 |

---

> 明细：`review_round2_parsed.json`。
