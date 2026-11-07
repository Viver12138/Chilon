---
type: report
title: 教材映射 v8（第五批 64 条终检修正，in-sample）
updated: 2026-11-07
status: map-v8
---

# 教材映射 v8：第五批全量终检 64 条错判修正（in-sample）

> 输入：`var/textbook_mapping/mapped_1797_reviewed_round5.json`（teacher **1797** / model **0**）、
> `var/textbook_mapping/review_round5_parsed.json`（671 行；64 条 full 不一致）、
> v7 引擎 `tools/kb_textbook_map_v7.py` 与 `mapped_1797_v7.json`；
> 输出：`tools/kb_textbook_map_v8.py`、`mapped_1797_v8.json`、`mapped_1797_reviewed_v8.json`、
> `mapped_1797_v8_eval.json`。
>
> **本轮没有 fresh holdout**：1797 块全部已有教师标注，64 条目标是 v7 在第五批暴露的错判。
> v8 是在这 64 条上做 **in-sample** 规则拟合；**1558/1561 不是泛化能力、不是准确率承诺**，
> 不得写入 README / 设计 master / 对外口径。

## 0. 结论摘要（先看这里）

| 项 | v7 | v8 | 判定 |
| --- | ---: | ---: | --- |
| 64 条目标修复 | — | **64/64** | 全修 |
| new harmed（v7 对 → v8 错） | — | **0** | 通过 |
| 反样本守卫（v7→v8 标签不变） | — | **57/57** | 通过 |
| 1595 口径 exact（教师 kp 行） | 1494 | **1561** | +67 |
| 1595 口径 module | 1577 | **1583** | +6 |
| 第五批 round5 exact | 500/564 | **564/564** | +64，全修 |
| 全量 1797 v7→v8 变化 | — | **68 块**（64 目标 + 3 同向顺带 + 1 非内容行 model 标签） | 意外 0、目标缺失 0 |
| PG dry-run | — | **待写/变更 0** | 未 apply |
| vault 投影 dry-run | — | **write=0 / unchanged=5** | 未 apply |

**为什么是 1561 而不是 1558**：64 条目标全修 +64，另有 3 条 **历史仍错**（非本轮 64 目标）
被同向新规则顺带修好（`TB-B2-0243-1` 古典概型定义、`TB-B2-0160-1`/`TB-B2-0167-1` 线面垂直），
3 条都在 288 子集，因此 288 exact 238→241（是提升，不是回退），合计 1494+64+3=**1561/1595**。
另 1 条变化是教师判 non_content 的 `TB-B1-0154-2`（4.5 阅读材料续块）的 **model 标签**由
logarithm 变为 zero；其教师字段不变，reviewed 状态仍 non_content。

## 1. 口径与边界

- **教师覆盖**：1797/1797 全部 teacher（五批），PG 无 model 行；status mapped 1595 / non_content 191 / vocab_gap 11。
- **分母**：与 v7 报告同口径 —— 教师给了 kp 且模型侧非 non_content：
  360 `327` + 288 `270` + 310 `273` + 第四批 `156` + 第五批 `564` = **1590**；
  另报 **1595 口径**（教师给了 kp 的全部 1595 行；其中 5 行历史模型侧为 non_content，
  见 §2「已知错」）。两个口径下 v8 exact 都是 1561。
- **变更范围**：v8 = v7 复制 + 3 条 `V8_PRE_RULES`（仅调顺序，早于既有 PRI 规则）+
  39 条追加窄条件 `V8_RULES`（追加在 v6/v7 规则之后）。
  **未改** v3–v7 引擎、SECTION_KP/SEC_SKIP/MIN_SCORE/FILL_CONF、既有规则语义/阈值/排除词；
  **无 block_id 硬编码**；映射阶段不读教师标签。
- **数据边界**：PG 数据、vault、review_sheets、design master、README 均未改；未 commit。

## 2. 指标（v7 → v8，1595 口径）

| 子集 | 分母 | v7 exact | v8 exact | v7 module | v8 module |
| --- | ---: | ---: | ---: | ---: | ---: |
| 360 | 327 | 327 | 327 | 327 | 327 |
| 288 | 270 | 238 | 241 | 263 | 263 |
| 310 | 273 | 273 | 273 | 273 | 273 |
| 第四批 round4 | 156 | 156 | 156 | 156 | 156 |
| 第五批 round5 | 564 | 500 | 564 | 558 | 564 |
| **固定分母合计** | **1590** | **1494** | **1561** | **1577** | **1583** |
| **1595 口径合计（含 5 条历史模型 non_content）** | **1595** | **1494** | **1561** | **1577** | **1583** |

- 第五批 round5：exact **500→564/564**（64 条全修），module **558→564**。
- 288：exact **238→241/270**（+3 为 §0 所述历史同向顺带修正），module 263 不变。
- 360 / 310 / 第四批：exact 327/327、273/273、156/156 **完全不变**，module 亦不变。
- **still_wrong 34 条**：5 条为历史模型侧 non_content 的已知错（`TB-B1-0044-2`、`TB-B1-0045-1`、
  `TB-B1-0061-1`、`TB-B2-0228-1`、`TB-B4-0076-1`；教师给了 kp、模型历史 non_content，规则无法翻案）
  + 29 条为 360/288/310/第四批 历史仍错（v7 记录 32 条，其中 3 条被 v8 同向顺带修好；不属于本轮 64 目标）。
- 64 条 v7 命中层诊断：**v3_base 54 条、SEC 6 条、PRI 4 条**（2 条被 5.5 和差角规则抢、
  1 条被 6.3.4 三等分点坐标规则抢、1 条被 6.4.3 复习题数量积规则抢）。这与 v6→v7 的经验一致：
  大部分错判来自「v3 基线正文关键词 + 既有 PRI 无该窄条件」。

## 3. 64 条按错因分组（before / after）

> 每条：block_id | 节 | 教师标签 | v7 | v8 | v7 命中层。v8 规则依据见 §4 与源码内注释；
> 其中由 PRE 顺序修正的 5 条（倍角 3、6.3.4 综合运用 1、6.4.3 节导语 1）已标注在 §4。

### 一、分段函数（3.1/3.4）（6 条）

根因：v3 基线只按正文关键词命中「函数概念」，3.1 的既有「分段函数|分段」规则不覆盖这些「用 M(x) 表示最大者」「个税/阶梯计费」「正三角形面积 f(t)」块；3.4 的个税建模规则只认「函数模型/个税/应纳税」而 0102-2 只有一句结论、0109-1 是纯习题。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0075-2-p0075-02` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |
| `TB-B1-0077-1-p0077-01` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |
| `TB-B1-0077-2-p0077-02` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |
| `TB-B1-0078-1-p0078-01` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |
| `TB-B1-0102-2-p0102-02` | 3.4 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |
| `TB-B1-0109-1-p0109-01` | 3.4 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | v3_base |

### 二、函数模型与对数/零点（4.4.2/4.5/4.5.3）（11 条）

根因：4.4.2 节末「不同函数增长的差异」是函数模型/增长比较块，v3 按「对数函数」字面命中 log；4.5 节导语（函数的零点）与例2（二分法）v3 按「方程/对数」命中 log；4.5.3 的碳14、奖励方案、肉鸡、耗油量等应用续块没有既有 4.5.3 规则里的「个税/浮萍/国家统计局/二分法/三个方案」特征。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0143-1-p0143-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0144-1-p0144-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0145-1-p0145-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0146-1-p0146-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0149-1-p0149-01` | 4.5 | kp_02_11_zero | kp_02_09_logarithm | kp_02_11_zero | v3_base |
| `TB-B1-0153-1-p0153-01` | 4.5 | kp_02_11_zero | kp_02_09_logarithm | kp_02_11_zero | v3_base |
| `TB-B1-0156-2-p0156-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0159-2-p0159-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0160-3-p0160-03` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0161-3-p0161-03` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |
| `TB-B1-0163-2-p0163-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | v3_base |

### 三、倍角公式（5.5）（3 条）

根因：5.5 既有「和差角」PRI 规则优先命中（含「和(差)角」字样的二倍角推导正文），0228-2 落 SEC 也选到 sumdiff。需要 **PRE 规则**（早于既有 PRI）用「倍角公式/二倍角的正弦/1-2sin²2α」窄特征接管；教师=sumdiff 的 0229-1（tan4α=sin4α/cos4α）不含这些短语。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0227-4-p0227-04` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | PRI |
| `TB-B1-0228-1-p0228-01` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | PRI |
| `TB-B1-0228-2-p0228-02` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | SEC |

### 四、图象变换（5.6）（4 条）

根因：5.6 的 A/ω/φ 图象变换块被 v3 基线按 sin/cos 关键词判成「图象与性质」（graph）。用「参数 A,ω,φ」「改变 A 的取值」「图象上所有点的横/纵坐标缩短/伸长」窄特征；教师=graph 的 0240-1（你发现图象有什么变化）、0244-2（曲线上各点纵坐标变为 2 倍）、0247-1（选择题选项「横坐标伸长到原来的」）实测不命中。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0239-1-p0239-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | v3_base |
| `TB-B1-0241-1-p0241-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | v3_base |
| `TB-B1-0242-1-p0242-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | v3_base |
| `TB-B1-0242-2-p0242-02` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | v3_base |

### 五、三角函数应用（5.6 摩天轮 + 5.7）（9 条）

根因：5.7 教师把「建模/解析式」块标 graph、把「解答/应用练习」块标 apply；v3 基线一律按 sin/cos 命中 graph。按各块正文的设问/解答特征逐条窄命中（振子周期、求电流解析式、某简谐运动练习、温度曲线解答、吃水深度/进港/出港、造父变星等），与 graph 反样本互斥。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0245-2-p0245-02` | 5.6 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0249-2-p0249-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0250-2-p0250-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0251-2-p0251-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0252-2-p0252-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0253-2-p0253-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0254-1-p0254-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0255-1-p0255-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |
| `TB-B1-0256-1-p0256-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | v3_base |

### 六、平面向量基本定理与坐标/数量积（6.3/6.3.4）（7 条）

根因：v3 基线对 6.3 基本定理证明续块（λ1e1+λ2e2）按「坐标」字面命中 coordinate；6.3.4 数乘/共线/数量积坐标块被 v3 判成 concept（无既有规则）；0044-1 被 v7 三等分点坐标 PRI 抢走（教师=concept，需 PRE 规则用「用向量方…法证明你的结论」接管）。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0032-3-p0032-03` | 6.3 | kp_05_06_decompose | kp_05_02_coordinate | kp_05_06_decompose | v3_base |
| `TB-B2-0038-1-p0038-01` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | v3_base |
| `TB-B2-0039-1-p0039-01` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | v3_base |
| `TB-B2-0041-1-p0041-01` | 6.3.4 | kp_05_03_dot | kp_05_01_concept | kp_05_03_dot | v3_base |
| `TB-B2-0043-1-p0043-01` | 6.3.4 | kp_05_03_dot | kp_05_01_concept | kp_05_03_dot | v3_base |
| `TB-B2-0043-3-p0043-03` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | v3_base |
| `TB-B2-0044-1-p0044-01` | 6.3.4 | kp_05_01_concept | kp_05_02_coordinate | kp_05_01_concept | PRI |

### 七、平面向量应用（6.3 例2 + 6.4）（4 条）

根因：6.4 应用块 v3/SEC 按数量积/垂直关键词命中 dot/perpendicular；0034-1 是 6.3 例2「用向量方法证明直角三角形」解答块，被 v3 按坐标命中。用「三步曲/旅行包/河宽/航程最短」与「因此 CA⊥CB」窄特征。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0034-1-p0034-01` | 6.3 | kp_05_08_apply | kp_05_02_coordinate | kp_05_08_apply | v3_base |
| `TB-B2-0046-1-p0046-01` | 6.4 | kp_05_08_apply | kp_05_03_dot | kp_05_08_apply | SEC |
| `TB-B2-0047-2-p0047-02` | 6.4 | kp_05_08_apply | kp_05_03_dot | kp_05_08_apply | SEC |
| `TB-B2-0048-1-p0048-01` | 6.4 | kp_05_08_apply | kp_05_04_perpendicular | kp_05_08_apply | SEC |

### 八、解三角形（6.4.3）（6 条）

根因：6.4.3 节导语（余弦定理、正弦定理）被 v7 复习题数量积 PRI 抢成 dot（需 PRE）；其余解答/练习续块被 v3 判成 concept（正弦定理求边、应用举例、游泳/水流、余弦定理中线、测量方案设计）。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0049-1-p0049-01` | 6.4.3 | kp_04_09_cosine | kp_05_03_dot | kp_04_09_cosine | PRI |
| `TB-B2-0055-1-p0055-01` | 6.4.3 | kp_04_08_sine | kp_05_01_concept | kp_04_08_sine | v3_base |
| `TB-B2-0055-3-p0055-03` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | v3_base |
| `TB-B2-0059-2-p0059-02` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | v3_base |
| `TB-B2-0060-3-p0060-03` | 6.4.3 | kp_04_09_cosine | kp_05_01_concept | kp_04_09_cosine | v3_base |
| `TB-B2-0061-2-p0061-02` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | v3_base |

### 九、直线与平面/平面与平面垂直（8.6.2）（3 条）

根因：8.6.2 的线面垂直定义/判定/距离、面面垂直性质块被 v3 按 position/area_volume 命中；既有 8.6.2 规则只覆盖线面角与棱台体积。用「直线与平面垂直」「平面与平面垂直」（neg 二面角）窄命中；棱台体积块由既有 PRI 先命中、二面角块被 neg 排除。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0156-1-p0156-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | v3_base |
| `TB-B2-0157-1-p0157-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_02_area_volume | kp_08_05_perpendicular | v3_base |
| `TB-B2-0166-1-p0166-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | v3_base |

### 十、用样本估计总体/频率分布直方图（9.2）（1 条）

根因：9.2 节导语（统计图表整理数据/频率分布）被 SEC 节级重选判成 sample；用节标题与「统计图表/频率分布」窄命中，0200-2（教师=sample）不含这些词。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0200-1-p0200-01` | 9.2 | kp_10_02_histogram | kp_10_01_sample | kp_10_02_histogram | SEC |

### 十一、古典概型（10.1）（6 条）

根因：10.1 只有 10.3 有古典概型规则；10.1.3 古典概型定义/例题块被 v3 判成事件（event）。按定义句/例题特征逐条窄命中；教师=event 的相邻块（0243-2/0245-2/0250-1/0252-2）实测不命中。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B2-0242-3-p0242-03` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |
| `TB-B2-0244-1-p0244-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |
| `TB-B2-0244-2-p0244-02` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |
| `TB-B2-0245-1-p0245-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |
| `TB-B2-0246-1-p0246-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |
| `TB-B2-0247-2-p0247-02` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | v3_base |

### 十二、导数（5.2/5.2.2/5.3）（3 条）

根因：5.2 基本初等函数导数公式表/1/x、√x 求导块被 v3 按切线命中 tangent；5.2.2 牛顿法首块（用「作切线」的方法求零点）被 v3 判 tangent；5.3 饮料瓶利润最值应用题头被 v3 判monotonic（既有 5.3 最优化规则只认容积/用料最省/方盒）。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B5-0079-1-p0079-01` | 5.2 | kp_03_01_compute | kp_03_02_tangent | kp_03_01_compute | v3_base |
| `TB-B5-0088-1-p0088-01` | 5.2.2 | kp_03_06_zeros | kp_03_02_tangent | kp_03_06_zeros | v3_base |
| `TB-B5-0101-2-p0101-02` | 5.3 | kp_03_04_extremum | kp_03_03_monotonic | kp_03_04_extremum | v3_base |

### 十三、排列组合（选必三 6.3）（1 条）

根因：6.3 章末复习题（分票/听讲座/多边形对角线）教师=combination，SEC 节级重选按二项式定理命中 binomial；用「不同分法的种数/不同的选择/对角线的条数」窄命中。

| block_id | 节 | 教师 | v7 | v8 | v7 命中层 |
| --- | --- | --- | --- | --- | --- |
| `TB-B4-0042-3-p0042-03` | 6.3 | kp_11_03_combination | kp_11_05_binomial | kp_11_03_combination | SEC |


## 4. 规则 / 顺序修正与依据

### 4.1 新增规则总览

- `V8_PRE_RULES`（3 条，**必须先于既有 PRIORITY_RULES**，只用于纠正既有规则误命中）：
  1. 5.5 倍角公式（「倍角公式｜二倍角的正弦｜1−2sin²2α」）—— 0227-4/0228-1 被既有和差角 PRI
     抢成 sumdiff、0228-2 落 SEC 也错；5.5 内教师=sumdiff 的 17 块（含 0229-1 tan4α）不含这些短语；
  2. 6.3.4 综合运用（「用向量方…(第11题)…法证明你的结论」）—— 0044-1 被三等分点坐标 PRI 抢成
     coordinate，教师=concept；其他块不含「你的结论」；
  3. 6.4.3 节导语（「一个三角形含有各种各样的几何量｜6.4.3 余弦定理、正弦定理」）—— 0049-1
     被复习题数量积 PRI 抢成 dot，教师=cosine；同节应用举例块含「应用举例」不命中。
- `V8_RULES`（39 条，追加在既有规则之后）：13 个错因组，逐条 note 见源码；每条都先限定
  book+section，再用 OCR 稳定短语/设问模板/公式连写命中，并用同节教师已对的相邻块做反样本核对
  （见 §4.3）。

### 4.2 每条新规则修复的 64 目标数

| 规则（V8_PRE / V8_RULES note） | 修复的 64 目标数 |
| --- | ---: |
| 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 5 |
| 4.4.2 节内不同函数增长的差异 | 4 |
| 5.6 节内 A/ω/φ 对图象的变换 | 4 |
| 3.1 节内个税/阶梯分段函数应用 | 3 |
| 5.5 节内倍角公式（二倍角推导/例5 cos4α） | 3 |
| 5.7 节内港口潮汐/货船进港应用 | 3 |
| 6.4 节内向量方法应用（三步曲/力/航行） | 3 |
| 10.1 节内古典概型（掷两枚骰子） | 2 |
| 4.5 节内函数零点/二分法 | 2 |
| 6.3.4 节内数量积的坐标表示 | 2 |
| 8.6.2 节内直线与平面垂直 | 2 |
| 10.1 节内古典概型例题（单选题） | 1 |
| 10.1 节内古典概型定义 | 1 |
| 10.1 节内古典概型（抽样概率比较 0.167） | 1 |
| 10.1 节内古典概型（摸球 20 种等可能） | 1 |
| 3.1 节内 max 型分段函数表示（用 M(x) 表示最大者） | 1 |
| 3.4 节内分段函数应用（经济效益分析续块） | 1 |
| 3.4 节内分段函数应用（试求函数解析式） | 1 |
| 5.2 节内基本初等函数导数公式 | 1 |
| 5.2.2 节内牛顿法求零点 | 1 |
| 5.3 节内最优化应用（饮料瓶利润） | 1 |
| 5.6 节内三角模型应用（摩天轮解答续块） | 1 |
| 5.7 节内习题5.7 综合运用 | 1 |
| 5.7 节内交变电流函数解析式 | 1 |
| 5.7 节内振子周期求解 | 1 |
| 5.7 节内温度曲线解答 | 1 |
| 5.7 节内简谐运动练习 | 1 |
| 6.3 节内向量法应用（证明直角三角形） | 1 |
| 6.3 节内平面向量基本定理（基底分解） | 1 |
| 6.3 节内排列组合综合（计数问题） | 1 |
| 6.3.4 节内坐标判断三点共线 | 1 |
| 6.3.4 节内坐标运算（垂直/共线求坐标） | 1 |
| 6.3.4 节内数乘运算的坐标表示 | 1 |
| 6.3.4 节内综合运用（用向量方法证明你的结论） | 1 |
| 6.4.3 节内余弦定理证明中线公式 | 1 |
| 6.4.3 节内正弦定理解三角形 | 1 |
| 6.4.3 节内解三角形应用举例 | 1 |
| 6.4.3 节内解三角形应用（测量方案设计） | 1 |
| 6.4.3 节内解三角形应用（游泳/水流） | 1 |
| 6.4.3 节导语（余弦定理、正弦定理） | 1 |
| 8.6.2 节内平面与平面垂直 | 1 |
| 9.2 节内用样本估计总体（频率分布） | 1 |

> 39 条规则中 30 条命中 ≥1 个目标；其余规则命中同 kp 块（不改标签，只改 rule 溯源字段），
> 例如 8.6.2 线面垂直规则顺带修正 2 条历史错块。

### 4.3 反样本守卫（关键样本）

| block_id | 期望 v8 | 说明 |
| --- | --- | --- |
| `TB-B1-0143-2-p0143-02` | kp_02_09_logarithm | 4.4.2 对数块含「增长速度不同」不增长规则抢走 |
| `TB-B1-0229-1-p0229-01` | kp_04_03_sumdiff | 5.5 tan4α=sin4α/cos4α 块不被倍角 PRE 规则抢走 |
| `TB-B1-0247-1-p0247-01` | kp_04_05_graph | 5.6 选择题选项「横坐标伸长到原来的」不被变换规则抢走 |
| `TB-B1-0253-1-p0253-01` | （空） | 5.7 潮汐导语（教师=graph）不被港口应用规则抢改 |
| `TB-B2-0032-4-p0032-04` | kp_05_02_coordinate | 6.3 零向量 λ1e1+λ2e2 块不被分解规则抢走 |
| `TB-B2-0047-3-p0047-03` | kp_05_03_dot | 6.4 力的夹角块含「省力」不被应用规则抢走 |
| `TB-B2-0164-1-p0164-01` | kp_08_06_angle | 8.6.2 二面角块被 neg「二面角」挡住 |
| `TB-B2-0243-2-p0243-02` | kp_10_13_event | 10.1 抽男生概率例题含「古典概型」不被抢走 |
| `TB-B5-0102-1-p0102-01` | kp_03_03_monotonic | 5.3 利润单调性分析块不被最优化规则抢走 |
| `TB-B4-0042-1-p0042-01` | kp_11_05_binomial | 选必三 6.3 章末复习导语不被组合规则抢走 |

> 完整 57 条守卫见 `mapped_1797_v8_eval.json` 的 `guard_check`；57/57 保持 v7 标签不变。

## 5. 全量 1797 变化审计（v7 → v8）

- 变化 **68 块**：**64 目标** + **3 同向顺带**（`TB-B2-0243-1`、`TB-B2-0160-1`、`TB-B2-0167-1`，
  均为 288 子集历史仍错 → 对的净收益）+ **1 非内容行 model 标签**（`TB-B1-0154-2`，教师 non_content 不变）。
- `unexpected_changes = []`、`missing_targets = []`；无「目标外教师 kp 行」被改。
- reviewed_v8 教师 1797 行：**除 model_primary/model_secondary/model_status 外逐字段与 round5 0 差异**；
  teacher_version 逐行保留（五批计数见 §6）。教师行的 kp_primary/status/teacher_kp/teacher_module/
  teacher_note/teacher_version 均未动。
- 映射 status（模型侧）：mapped 1747 / non_content 43 / vocab_gap 7；规则命中层
  v3_base 1113 / CAT 5 / SEC 233 / PRI 428 / FILL 16 / SUM 2。

| block_id | 节 | 教师 | v7 | v8 | 新规则 | 类型 |
| --- | --- | --- | --- | --- | --- | --- |
| `TB-B2-0242-3-p0242-03` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型定义 | 目标 64 |
| `TB-B2-0243-1-p0243-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型定义 | 同向顺带 |
| `TB-B2-0244-1-p0244-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型例题（单选题） | 目标 64 |
| `TB-B2-0244-2-p0244-02` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型（掷两枚骰子） | 目标 64 |
| `TB-B2-0245-1-p0245-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型（掷两枚骰子） | 目标 64 |
| `TB-B2-0246-1-p0246-01` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型（摸球 20 种等可能） | 目标 64 |
| `TB-B2-0247-2-p0247-02` | 10.1 | kp_10_04_classical | kp_10_13_event | kp_10_04_classical | 10.1 节内古典概型（抽样概率比较 0.167） | 目标 64 |
| `TB-B1-0075-2-p0075-02` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.1 节内 max 型分段函数表示（用 M(x) 表示最大者） | 目标 64 |
| `TB-B1-0077-1-p0077-01` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.1 节内个税/阶梯分段函数应用 | 目标 64 |
| `TB-B1-0077-2-p0077-02` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.1 节内个税/阶梯分段函数应用 | 目标 64 |
| `TB-B1-0078-1-p0078-01` | 3.1 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.1 节内个税/阶梯分段函数应用 | 目标 64 |
| `TB-B1-0102-2-p0102-02` | 3.4 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.4 节内分段函数应用（经济效益分析续块） | 目标 64 |
| `TB-B1-0109-1-p0109-01` | 3.4 | kp_02_13_segment | kp_02_01_concept | kp_02_13_segment | 3.4 节内分段函数应用（试求函数解析式） | 目标 64 |
| `TB-B1-0143-1-p0143-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.4.2 节内不同函数增长的差异 | 目标 64 |
| `TB-B1-0144-1-p0144-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.4.2 节内不同函数增长的差异 | 目标 64 |
| `TB-B1-0145-1-p0145-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.4.2 节内不同函数增长的差异 | 目标 64 |
| `TB-B1-0146-1-p0146-01` | 4.4.2 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.4.2 节内不同函数增长的差异 | 目标 64 |
| `TB-B1-0149-1-p0149-01` | 4.5 | kp_02_11_zero | kp_02_09_logarithm | kp_02_11_zero | 4.5 节内函数零点/二分法 | 目标 64 |
| `TB-B1-0153-1-p0153-01` | 4.5 | kp_02_11_zero | kp_02_09_logarithm | kp_02_11_zero | 4.5 节内函数零点/二分法 | 目标 64 |
| `TB-B1-0154-2-p0154-02` | 4.5 | non_content | kp_02_09_logarithm | kp_02_11_zero | 4.5 节内函数零点/二分法 | 非内容行 model 标签 |
| `TB-B1-0156-2-p0156-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 目标 64 |
| `TB-B1-0159-2-p0159-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 目标 64 |
| `TB-B1-0160-3-p0160-03` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 目标 64 |
| `TB-B1-0161-3-p0161-03` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 目标 64 |
| `TB-B1-0163-2-p0163-02` | 4.5.3 | kp_02_12_abstract | kp_02_09_logarithm | kp_02_12_abstract | 4.5.3 节内函数模型应用（衰减/奖励/成本等） | 目标 64 |
| `TB-B5-0079-1-p0079-01` | 5.2 | kp_03_01_compute | kp_03_02_tangent | kp_03_01_compute | 5.2 节内基本初等函数导数公式 | 目标 64 |
| `TB-B5-0088-1-p0088-01` | 5.2.2 | kp_03_06_zeros | kp_03_02_tangent | kp_03_06_zeros | 5.2.2 节内牛顿法求零点 | 目标 64 |
| `TB-B5-0101-2-p0101-02` | 5.3 | kp_03_04_extremum | kp_03_03_monotonic | kp_03_04_extremum | 5.3 节内最优化应用（饮料瓶利润） | 目标 64 |
| `TB-B1-0227-4-p0227-04` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | 5.5 节内倍角公式（二倍角推导/例5 cos4α） | 目标 64 |
| `TB-B1-0228-1-p0228-01` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | 5.5 节内倍角公式（二倍角推导/例5 cos4α） | 目标 64 |
| `TB-B1-0228-2-p0228-02` | 5.5 | kp_04_04_double | kp_04_03_sumdiff | kp_04_04_double | 5.5 节内倍角公式（二倍角推导/例5 cos4α） | 目标 64 |
| `TB-B1-0239-1-p0239-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | 5.6 节内 A/ω/φ 对图象的变换 | 目标 64 |
| `TB-B1-0241-1-p0241-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | 5.6 节内 A/ω/φ 对图象的变换 | 目标 64 |
| `TB-B1-0242-1-p0242-01` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | 5.6 节内 A/ω/φ 对图象的变换 | 目标 64 |
| `TB-B1-0242-2-p0242-02` | 5.6 | kp_04_06_transform | kp_04_05_graph | kp_04_06_transform | 5.6 节内 A/ω/φ 对图象的变换 | 目标 64 |
| `TB-B1-0245-2-p0245-02` | 5.6 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.6 节内三角模型应用（摩天轮解答续块） | 目标 64 |
| `TB-B1-0249-2-p0249-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内振子周期求解 | 目标 64 |
| `TB-B1-0250-2-p0250-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内交变电流函数解析式 | 目标 64 |
| `TB-B1-0251-2-p0251-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内简谐运动练习 | 目标 64 |
| `TB-B1-0252-2-p0252-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内温度曲线解答 | 目标 64 |
| `TB-B1-0253-2-p0253-02` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内港口潮汐/货船进港应用 | 目标 64 |
| `TB-B1-0254-1-p0254-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内港口潮汐/货船进港应用 | 目标 64 |
| `TB-B1-0255-1-p0255-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内港口潮汐/货船进港应用 | 目标 64 |
| `TB-B1-0256-1-p0256-01` | 5.7 | kp_04_11_apply | kp_04_05_graph | kp_04_11_apply | 5.7 节内习题5.7 综合运用 | 目标 64 |
| `TB-B2-0032-3-p0032-03` | 6.3 | kp_05_06_decompose | kp_05_02_coordinate | kp_05_06_decompose | 6.3 节内平面向量基本定理（基底分解） | 目标 64 |
| `TB-B2-0034-1-p0034-01` | 6.3 | kp_05_08_apply | kp_05_02_coordinate | kp_05_08_apply | 6.3 节内向量法应用（证明直角三角形） | 目标 64 |
| `TB-B4-0042-3-p0042-03` | 6.3 | kp_11_03_combination | kp_11_05_binomial | kp_11_03_combination | 6.3 节内排列组合综合（计数问题） | 目标 64 |
| `TB-B2-0038-1-p0038-01` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | 6.3.4 节内数乘运算的坐标表示 | 目标 64 |
| `TB-B2-0039-1-p0039-01` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | 6.3.4 节内坐标判断三点共线 | 目标 64 |
| `TB-B2-0041-1-p0041-01` | 6.3.4 | kp_05_03_dot | kp_05_01_concept | kp_05_03_dot | 6.3.4 节内数量积的坐标表示 | 目标 64 |
| `TB-B2-0043-1-p0043-01` | 6.3.4 | kp_05_03_dot | kp_05_01_concept | kp_05_03_dot | 6.3.4 节内数量积的坐标表示 | 目标 64 |
| `TB-B2-0043-3-p0043-03` | 6.3.4 | kp_05_02_coordinate | kp_05_01_concept | kp_05_02_coordinate | 6.3.4 节内坐标运算（垂直/共线求坐标） | 目标 64 |
| `TB-B2-0044-1-p0044-01` | 6.3.4 | kp_05_01_concept | kp_05_02_coordinate | kp_05_01_concept | 6.3.4 节内综合运用（用向量方法证明你的结论） | 目标 64 |
| `TB-B2-0046-1-p0046-01` | 6.4 | kp_05_08_apply | kp_05_03_dot | kp_05_08_apply | 6.4 节内向量方法应用（三步曲/力/航行） | 目标 64 |
| `TB-B2-0047-2-p0047-02` | 6.4 | kp_05_08_apply | kp_05_03_dot | kp_05_08_apply | 6.4 节内向量方法应用（三步曲/力/航行） | 目标 64 |
| `TB-B2-0048-1-p0048-01` | 6.4 | kp_05_08_apply | kp_05_04_perpendicular | kp_05_08_apply | 6.4 节内向量方法应用（三步曲/力/航行） | 目标 64 |
| `TB-B2-0049-1-p0049-01` | 6.4.3 | kp_04_09_cosine | kp_05_03_dot | kp_04_09_cosine | 6.4.3 节导语（余弦定理、正弦定理） | 目标 64 |
| `TB-B2-0055-1-p0055-01` | 6.4.3 | kp_04_08_sine | kp_05_01_concept | kp_04_08_sine | 6.4.3 节内正弦定理解三角形 | 目标 64 |
| `TB-B2-0055-3-p0055-03` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | 6.4.3 节内解三角形应用举例 | 目标 64 |
| `TB-B2-0059-2-p0059-02` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | 6.4.3 节内解三角形应用（游泳/水流） | 目标 64 |
| `TB-B2-0060-3-p0060-03` | 6.4.3 | kp_04_09_cosine | kp_05_01_concept | kp_04_09_cosine | 6.4.3 节内余弦定理证明中线公式 | 目标 64 |
| `TB-B2-0061-2-p0061-02` | 6.4.3 | kp_04_11_apply | kp_05_01_concept | kp_04_11_apply | 6.4.3 节内解三角形应用（测量方案设计） | 目标 64 |
| `TB-B2-0156-1-p0156-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | 8.6.2 节内直线与平面垂直 | 目标 64 |
| `TB-B2-0157-1-p0157-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_02_area_volume | kp_08_05_perpendicular | 8.6.2 节内直线与平面垂直 | 目标 64 |
| `TB-B2-0160-1-p0160-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | 8.6.2 节内直线与平面垂直 | 同向顺带 |
| `TB-B2-0166-1-p0166-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | 8.6.2 节内平面与平面垂直 | 目标 64 |
| `TB-B2-0167-1-p0167-01` | 8.6.2 | kp_08_05_perpendicular | kp_08_03_position | kp_08_05_perpendicular | 8.6.2 节内直线与平面垂直 | 同向顺带 |
| `TB-B2-0200-1-p0200-01` | 9.2 | kp_10_02_histogram | kp_10_01_sample | kp_10_02_histogram | 9.2 节内用样本估计总体（频率分布） | 目标 64 |

## 6. reviewed_v8 与产物一致性

- `mapped_1797_v8.json`：1797 块、block_id 唯一 1797；每条含 v8 `kp_primary/kp_secondary/status/rule/reason`。
- `mapped_1797_reviewed_v8.json`：count 1797，teacher_count **1797**；status
  mapped 1595 / non_content 191 / vocab_gap 11（= round5 教师判定不变）；
  每行 `model_primary/model_secondary/model_status` 已更新为 v8 预测（便于溯源），其余教师字段保留。
- 校验数字：教师行非 model_* 字段差异 **0**；teacher_version 丢失 **0**；
  teacher_version 计数 `{'textbook-review-2026-11-06': 360, 'textbook-review-v4-round2-2026-11-06': 288, 'textbook-review-v5-round3-2026-11-07': 310, 'textbook-review-v6-round4-2026-11-07': 168, 'textbook-review-v7-round5-2026-11-07': 671}`。
- `mapped_1797_v8_eval.json`：metrics / target_check（64 行 v3,v6,v7,v8 before-after）/
  guard_check（57）/ fixed（67）/ harmed（0）/ still_wrong（34）/ changes_v7_to_v8（68 行完整审计）。

## 7. PG / vault dry-run（均未 apply）

### 7.1 PG dry-run

命令：

```powershell
.venv\Scripts\python.exe tools/kb_textbook_pg_draft.py `
  --reviewed var/textbook_mapping/mapped_1797_reviewed_v8.json `
  --model-version textbook-map-v8-2026-11-07 `
  --backup var/textbook_mapping/backup_pg_draft_before_v8_2026-11-07.json
```

输出（关键行）：

```text
[dry-run] 输入 mapped_1797_reviewed_v8.json；model_version textbook-map-v8-2026-11-07；备份 backup_pg_draft_before_v8_2026-11-07.json
[dry-run] rows 1797；textbook chunks 1797；missing chunk 0；duplicate 0；teacher 1797 / model 0；表存在=True；待写/变更 0
状态 {'non_content': 191, 'mapped': 1595, 'vocab_gap': 11}
```

判定：**待写/变更 0**（rows 1797、missing 0、duplicate 0、teacher 1797 / model 0、表存在=True；
status non_content 191 / mapped 1595 / vocab_gap 11）。**未 apply**；备份文件
`var/textbook_mapping/backup_pg_draft_before_v8_2026-11-07.json` 已生成（dry-run 备份用途）。
原因：v8 只改未来自动映射，PG 里已是全教师行、teacher 字段与 round5 完全一致。

### 7.2 vault 投影 dry-run

命令：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe tools/project_restricted_corpus.py `
  --vault "<vault 路径>" --only textbook --force-generated
```

输出（关键行）：

```text
==============================================================================
PG → Obsidian：受限资料投影（模拟题 / 教材）
模式：dry-run　only=textbook　force_generated=True
vault：<vault 路径>
==============================================================================
DB：容器 chilon-pg-corpus env（127.0.0.1:55495/chilon）
[读库] mock 67 套 / 931 chunks；textbook 5 册 / 1797 chunks
[计划] 文件：write=0 unchanged=5 skip_human=0 skip_foreign=0 skip_conflict=0
        模拟：0 set / 0 卡；教材：5 册 / 1797 块；索引：0
        教材块级链接：teacher=1595 model=0 （链接合计 1595）；vocab_gap=11 non_content=191 无标注=0 缺主标注=0
        PDF 匹配：mock exact=0 fuzzy=0 none=0；教材 exact=5 fuzzy=0 none=0
[文档] 
[dry-run] 未写任何文件。确认后加 --apply。

报告：D:\Chilon\var\projection\report.md
manifest：D:\Chilon\var\projection\manifest.json
```

判定：**write=0 / unchanged=5**（教材 5 册 1797 块；teacher=1595 / model=0 链接；vocab_gap=11、
non_content=191 无链接；缺主标注 0）。**未 apply、未写 vault**。
（投影工具在 dry-run 也会刷新 `var/projection/report.md` 与 `manifest.json` 的 dry-run 记录，
这是工具既有行为，不在本任务写入范围内、不影响 vault/PG。）

## 8. 局限与后续建议

1. **无 fresh holdout（最强声明）**：1797 块已全部被教师标注，本轮没有、也无法构造
   不受 v8 规则调参污染的留出集。v8 的 64/64、1561/1595 都是 **in-sample** 数字；
   **不能表述为准确率、泛化能力或对未来的承诺**。第五批在 v7 下 500/564 的数字才曾是相对干净的
   估计，但它现在也被用于拟合 v8 了。
2. **部分 64 条规则依赖单块特征短语**（如 `0.167`、`H=55sin`、`用向量方…法证明你的结论`、
   「造父/变星/天安门」）。这些不是 block_id 硬编码，但对 OCR 变体/改版教材的稳健性未经验证；
   若未来拿到新教材，建议先抽样人工标注做 fresh holdout 再评估，而不是直接信 1561。
3. **教师邻块标签存在噪声**：同一节内同类块可能被教师标成不同 kp（如 10.1 古典概型例题
   0243-2 标 event、0244-1 标 classical；5.7 建模块 graph、解答块 apply）。v8 只能拟合现有标签，
   这不是「数学上更正确」的证明。
4. **剩余 34 条 still_wrong**：29 条为历史批仍错（不属于本轮 64），5 条是历史模型侧 non_content
   的已知错，规则层面无法翻案（需人工/重新标注）。是否继续修 29 条应作为独立任务逐条诊断，
   并同样警惕 in-sample 过拟合。
5. **词表与非内容**：11 条 vocab_gap、191 条 non_content 建议作为词表缺口/非内容验收清单；
   不要用模型预测回填这些行。
6. **PG/vault 建议**：本轮已用 dry-run 证明 0 变更；若未来要把 v8 用于自动映射新块，
   先冻结规则版本、补 fresh holdout、再决定是否 apply。

## 9. 复现命令与文件清单

```powershell
# 1) 全量映射（系统 python；不读教师标签）
python tools/kb_textbook_map_v8.py --stage map

# 2) 评估 + reviewed_v8（系统 python；读教师标签）
python tools/kb_textbook_map_v8.py --stage eval

# 3) PG dry-run（.venv，含 psycopg；不 apply）
.venv\Scripts\python.exe tools/kb_textbook_pg_draft.py `
  --reviewed var/textbook_mapping/mapped_1797_reviewed_v8.json `
  --model-version textbook-map-v8-2026-11-07 `
  --backup var/textbook_mapping/backup_pg_draft_before_v8_2026-11-07.json

# 4) vault 投影 dry-run（不 apply）
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe tools/project_restricted_corpus.py `
  --vault "<vault 路径>" --only textbook --force-generated
```

| 文件 | 说明 |
| --- | --- |
| `tools/kb_textbook_map_v8.py` | v8 引擎（v7 复制 + V8_PRE_RULES 3 + V8_RULES 39 + 顺序 + 五批评估） |
| `var/textbook_mapping/mapped_1797_v8.json` | v8 全量映射 1797 |
| `var/textbook_mapping/mapped_1797_v8_batch.txt` | v8 批处理文本 |
| `var/textbook_mapping/mapped_1797_reviewed_v8.json` | teacher 1797 行（教师字段保留、model_* 更新v8） |
| `var/textbook_mapping/mapped_1797_v8_eval.json` | 指标 / 64 目标 / 57 守卫 / 67 fixed / 0 harmed / 68 变化审计 |
| `var/textbook_mapping/backup_pg_draft_before_v8_2026-11-07.json` | PG dry-run 前备份 |

> 未修改：v3–v7 引擎、PG 数据、vault、review_sheets、design master、README；未 commit、未跑 alembic、未 source `.env`。

