---
type: report
title: 教材 v4 复核抽样（20%，288 块）
updated: 2026-11-06
status: sample-pending-review
---

# 教材 v4 复核抽样（20%，288 块）

> 目标 **288** 块 = 1437 个 model 块 × 20%（沿用上一轮 360=1797×20% 的口径）；
> teacher 360 与 pilot 100 已复核过、均从抽样池剔除，可抽池 **1337**（实际抽样率 21.5%）；
> seed=20261106；未写 PG/vault、未调 OCR。

## 1. 抽样口径

- 池：`mapped_1797_reviewed_v4.json` 中 `review_status=model` 的 **1437** 块；
  剔除 teacher **360** 与 pilot **100**（两者都已有教师判定，避免重复复核）；
- 目标 288 = 1437 × 20%；从可抽池 1337 中抽，实际抽样率 21.5%；
- **稀有状态全量采集**：`vocab_gap` 全部（7）+ `non_content` 全部（13），共 20 块；
- 其余 **268** 块来自 `mapped`：先按册比例分配（最大余数法），册内按置信分层
  （≤0.70 / >0.70，每册至少 1 个低置信），再按章轮转抽取；
- 映射阶段不读教师标签；样本与 teacher 360、pilot 100 零重叠。

## 2. 样本构成

| 层 | 样本数 | 可抽池 |
| --- | ---: | ---: |
| vocab_gap | 7 | 7 |
| non_content | 13 | 13 |
| mapped（分层抽） | 268 | 1317 |
| **合计** | **288** | **1337** |

### 按册

| 册 | 样本 |
| --- | ---: |
| 必修第一册 | 104 |
| 必修第二册 | 78 |
| 选择性必修第一册 | 39 |
| 选择性必修第二册 | 25 |
| 选择性必修第三册 | 42 |
| **合计** | **288** |

### 按风险

| 风险 | 样本 |
| --- | ---: |
| 低置信（≤0.70） | 46 |
| 正常 mapped | 222 |
| vocab_gap | 7 |
| non_content | 13 |

## 3. 复核表字段与填写

复核表：`review_sheets/samples/教材映射复核_v4_剩余1437块_20pct_2026-11-06.xlsx`
（288 行，按 册 → 页码 → part → ordinal 排序；含 `词表` 与 `说明` sheet）。

| 列 | 含义 |
| --- | --- |
| `模型模块` / `模型primary` / `名称` / `模型secondary` / `置信` / `理由` | v4 模型候选（**待教师判定**） |
| `v4规则` | 修正层来源（`v3_base` / `SEC:…` / `PRI:…` / `FILL:…` / `CAT` / `SUM`），便于定位为什么改 |
| `v3模型primary` | 上一版候选，便于对比 v3→v4 变化 |
| `教师模块` / `教师考点` | **请填写**；模块 17 项、考点 120 项下拉（`词表` sheet） |
| `备注` | 请填写：错因/建议/边界说明 |

回填后把文件放回 `review_sheets/filled/`，再解析：与 teacher 360 一起重算 reviewed/PG，
并按 `textbook_block_annotations` 重投影 Obsidian 块级链接。

## 4. 校验（已实测）

- 288 行、block_id **288 唯一**、与 `sample_review_v4_20pct_2026-11-06.json` 完全一致；
- 与 teacher 360、pilot 100 **零重叠**；全部行 `review_status=model`；
- 完整原文非空（42–2589 字符）、按字面字符串存储（无公式注入）、教师列留空；
- 数据校验下拉：教师模块 `Q2:Q289`、教师考点 `R2:R289`；冻结首行 + 自动筛选。

## 5. 边界

- 这是**待复核**样本，不是结论；回填后才有质量数字。
- 稀有小类全量采集（gap/non_content）会让样本风险构成与全量略有偏离；
  `mapped` 层按册/置信分层接近比例抽样，可用于估计 mapped 块的准确率，但**不能直接外推全量**。
- pilot 100 块的逐块教师标签仍未入库（历史欠账），本表将其排除，不重复占用教师时间。

## 6. 含 pilot 回采版本（`--include-pilot`）

为补回 pilot 100 块**缺失的逐块教师标签**，同一抽样工具支持 `--include-pilot`，生成第二张表：

| 项 | 值 |
| --- | --- |
| 文件 | `review_sheets/samples/教材映射复核_v4_剩余1437块_20pct_含pilot_2026-11-06.xlsx` |
| 抽样池 | 1437（不剔除 pilot 100） |
| 样本 | 288 行 = 1437×20%；其中 **pilot 块 26 行**（重新采集） |
| 风险构成 | normal 213 / low_conf 44 / non_content 23 / vocab_gap 8 |
| 分册 | 必修一 101 / 必修二 76 / 选必一 40 / 选必二 25 / 选必三 43 |
| 校验 | 288 唯一 block_id、与 teacher 360 零重叠、教师列空、17/120 下拉、按册页排序 |

两套表**互不覆盖**：默认表（288 行、完全避开 pilot）与含 pilot 表（含 26 行 pilot 回采）。
若教师时间有限，建议先填默认 288 行；pilot 回采表可作为补充，或与默认表合并填写（避免同一 block 两处填）。

生成命令：

```powershell
python tools/kb_textbook_sample_review.py --include-pilot   # 含 pilot 回采表
python tools/kb_textbook_sample_review.py                   # 默认表（剔除 pilot）
```

---

> 工具：`tools/kb_textbook_sample_review.py`（`--stage sample|xlsx|all`，可换 `--percent`/`--seed`）；
> 抽样数据：`var/textbook_mapping/sample_review_v4_20pct_2026-11-06.json`（不提交）。
