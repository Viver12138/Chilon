---
type: report
title: 教材映射 v7（第四批 23 条 v6 不一致收敛与全量评估）
updated: 2026-11-07
status: map-v7
---

# 教材映射 v7：第四批 23 条不一致收敛 + 全量评估

> 输入：v6 规则引擎 + 第四批复核 168 块（20% 抽样）暴露的 **23 条「v6 错、教师对」** 不一致；
> 映射阶段**不读教师标签**，教师标签只在 eval 阶段读（四批共 1126 条，评估分母 **1026**）。
> 未改 v3–v6、未改 design master/README/review_sheets/抽样工具、未 commit、未跑 alembic。
>
> **一句话结论：23/23 修好、新 harmed 0、既有子集不回退；全量 exact 968→994/1026
>（仅按 23 条目标口径为 991/1026；另 3 条是同规则顺带修正的 288 批历史错块）。
> 671 model 行只有 9 条变化，逐条语义审计为“同向更正确”。但第四批已进入已标注集，
> 本轮没有 fresh holdout，994/1026 是 in-sample 数字，不能宣称泛化。**

---

## 1. 结论与关键数字

| 项 | v6 | v7 | 判读 |
| --- | ---: | ---: | --- |
| 23 条第四批目标 | 0/23 | **23/23** | 全部按教师标签修正 |
| 新 harmed（教师原本对的被改错） | — | **0** | 在 1026 条上逐条核验 |
| 360（327 条）exact | 327/327 | **327/327** | 不回退 |
| 288（270 条）exact | 235/270 | **238/270** | 顺带修正 3 条历史错块 |
| 310（273 条）exact | 273/273 | **273/273** | 不回退 |
| 第四批（156 条）exact | 133/156 | **156/156** | 23/23 修好，其余保持 |
| 合计（1026 条）exact | 968/1026 | **994/1026** | 仅 23 目标口径 **991/1026** |
| 合计 module | 1016/1026 | **1019/1026** | +3（0060-2 跨模块、0057-1/0058-1） |
| mapped 1797 v6→v7 变化 | — | **36** 块 | teacher 27 / model 9 |
| reviewed v7 teacher 1126 行 vs round4 | — | **0 差异** | 逐字段原样保留 |
| 反样本守卫 | — | **27/27** | 见 §4.3 |
| v6 历史 8 条目标 | 8/8 | **8/8** | v7 未回退 |

> 口径说明：**口径 A（仅 23 条目标）**= 327 + 235 + 273 + 156 = **991/1026**（module 1018）；
> **口径 B（v7 实际运行）**= 327 + 238 + 273 + 156 = **994/1026**（module 1019）。
> 差 3 条是 288 批里被同一条新规则顺带修正的历史错块（§5.2），不是隐藏的第 24–26 条目标。

---

## 2. 第四批 23 条 before/after 与命中层诊断

### 2.1 逐条 before/after

`V3/V4/V5/V6/V7` 均为 `kp_` 后的考点短名；`层` 是 v7 生效层（22 条新规则全部是 PRI）。

| block_id | 节 | 教师 | V3 | V4 | V5 | V6 | V7 | 层 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `TB-B1-0076-1-p0076-01` | 3.1 | `02_13_segment` | `02_01_concept` | `02_01_concept` | `02_01_concept` | `02_01_concept` | **`02_13_segment`** | PRI |
| `TB-B1-0151-2-p0151-02` | 4.5 | `02_11_zero` | `02_09_logarithm` | `02_09_logarithm` | `02_09_logarithm` | `02_09_logarithm` | **`02_11_zero`** | PRI |
| `TB-B1-0158-2-p0158-02` | 4.5.3 | `02_12_abstract` | `02_09_logarithm` | `02_09_logarithm` | `02_09_logarithm` | `02_09_logarithm` | **`02_12_abstract`** | PRI |
| `TB-B1-0191-2-p0191-02` | 5.2 | `04_02_identity` | `04_01_definition` | `04_01_definition` | `04_01_definition` | `04_01_definition` | **`04_02_identity`** | PRI |
| `TB-B1-0256-2-p0256-02` | 5.7 | `04_11_apply` | `04_05_graph` | `04_05_graph` | `04_05_graph` | `04_05_graph` | **`04_11_apply`** | PRI |
| `TB-B2-0030-1-p0030-01` | 6.2.4 | `05_01_concept` | `05_03_dot` | `05_03_dot` | `05_03_dot` | `05_03_dot` | **`05_01_concept`** | PRI |
| `TB-B2-0030-4-p0030-04` | 6.2.4 | `05_01_concept` | `05_03_dot` | `05_03_dot` | `05_03_dot` | `05_03_dot` | **`05_01_concept`** | PRI |
| `TB-B2-0032-2-p0032-02` | 6.3 | `05_06_decompose` | `05_02_coordinate` | `05_02_coordinate` | `05_02_coordinate` | `05_02_coordinate` | **`05_06_decompose`** | PRI |
| `TB-B2-0039-2-p0039-02` | 6.3.4 | `05_02_coordinate` | `05_01_concept` | `05_01_concept` | `05_01_concept` | `05_01_concept` | **`05_02_coordinate`** | PRI |
| `TB-B2-0057-1-p0057-01` | 6.4.3 | `04_11_apply` | `05_01_concept` | `05_01_concept` | `05_01_concept` | `05_01_concept` | **`04_11_apply`** | PRI |
| `TB-B2-0058-1-p0058-01` | 6.4.3 | `04_11_apply` | `05_01_concept` | `05_01_concept` | `05_01_concept` | `05_01_concept` | **`04_11_apply`** | PRI |
| `TB-B2-0071-2-p0071-02` | 6.4.3 | `05_08_apply` | `05_01_concept` | `05_01_concept` | `05_01_concept` | `05_01_concept` | **`05_08_apply`** | PRI |
| `TB-B2-0087-3-p0087-03` | 7.2 | `06_02_operation` | `06_01_concept` | `06_01_concept` | `06_01_concept` | `06_01_concept` | **`06_02_operation`** | PRI |
| `TB-B2-0095-1-p0095-01` | 7.3 | `06_04_geometric` | `06_01_concept` | `06_03_modulus` | `06_03_modulus` | `06_03_modulus` | **`06_04_geometric`** | PRI |
| `TB-B2-0159-1-p0159-01` | 8.6.2 | `08_06_angle` | `08_05_perpendicular` | `08_05_perpendicular` | `08_05_perpendicular` | `08_05_perpendicular` | **`08_06_angle`** | PRI |
| `TB-B2-0162-1-p0162-01` | 8.6.2 | `08_02_area_volume` | `08_06_angle` | `08_06_angle` | `08_06_angle` | `08_06_angle` | **`08_02_area_volume`** | PRI |
| `TB-B2-0211-1-p0211-01` | 9.2 | `10_03_central` | `10_02_histogram` | `10_02_histogram` | `10_02_histogram` | `10_02_histogram` | **`10_03_central`** | PRI |
| `TB-B2-0222-2-p0222-02` | 9.2.3 | `10_03_central` | `10_01_sample` | `10_01_sample` | `10_01_sample` | `10_01_sample` | **`10_03_central`** | PRI |
| `TB-B2-0233-1-p0233-01` | 9.3 | `10_03_central` | `10_10_regression` | `10_10_regression` | `10_10_regression` | `10_10_regression` | **`10_03_central`** | PRI |
| `TB-B2-0274-2-p0274-02` | 10.3 | `10_06_event` | `10_04_classical` | `10_04_classical` | `10_04_classical` | `10_04_classical` | **`10_06_event`** | PRI |
| `TB-B3-0150-1-p0150-01` | 3.3.2 | `09_05_ellipse` | `09_07_parabola` | `09_07_parabola` | `09_07_parabola` | `09_07_parabola` | **`09_05_ellipse`** | PRI |
| `TB-B5-0088-2-p0088-02` | 5.2.2 | `03_06_zeros` | `03_01_compute` | `03_01_compute` | `03_01_compute` | `03_01_compute` | **`03_06_zeros`** | PRI |
| `TB-B5-0091-2-p0091-02` | 5.3 | `03_03_monotonic` | `03_01_compute` | `03_01_compute` | `03_01_compute` | `03_01_compute` | **`03_03_monotonic`** | PRI |

### 2.2 命中层归因

| v6 命中层 | 条数 | 说明 |
| --- | ---: | --- |
| `v3_base` | **18** | v6 在这 18 块上没有任何 PRI/SEC 命中：节内缺规则、或 SEC_SKIP/无 section 候选；v3 基座按正文关键词选错（如“增长→对数”“方向/坐标→数量积/坐标”“面积→角度”） |
| `SEC:section_elect` | **5** | 0191-2（definition 8.0 > identity 4.5）、0095-1（modulus 10.5 > geometric 7.5）、0211-1（histogram 4.5 > central 4.0）、0222-2（sample 16 > central 14）、0274-2（classical 唯一候选） |
| PRI / CAT / SUM / FILL | 0 | 23 条都不落在既有规则命中面内，因此 v7 全部用**追加的窄条件 PRI 规则**接管 |

### 2.3 逐条诊断（v6 错因 → v7 修正）

| block_id | v6 错因 | v7 规则（语义） |
| --- | --- | --- |
| `TB-B1-0076-1` | 3.1 既有规则只认“分段函数/分段”，本块只有 `M(x)={…}` 分段公式与“解析式为”，无“分段”二字 | 3.1：`解析式为` + `\left\{\begin{array}` |
| `TB-B1-0151-2` | 4.5 节无 PRI（v6 二分法规则只挂 4.5.3）；v3 按“对数/零点”落到 logarithm | 4.5：小节标题 `4.5.2 用二分法求方程的近似解` |
| `TB-B1-0158-2` | 4.5.3 续块正文“增长情况/表 4.5-5”被 v3 判成对数函数 | 4.5.3：`三个方案/增长情况` |
| `TB-B1-0191-2` | 5.2 既有同角规则不认“1+tan²/求证恒等式”；SEC 把 definition 排第一 | 5.2：`1+tan²` 同角关系标志 |
| `TB-B1-0256-2` | 5.7 应用结论块无 graph 关键词，v3 落到 graph | 5.7：`消峰平谷`（电价方案结论） |
| `TB-B2-0030-1` | 块在 6.2.4（数量积节）下，实为**习题6.2** 向量作图/化简；v3 被数量积关键词带走 | 6.2.4：`作图验证/求作向量` |
| `TB-B2-0030-4` | 同上；块含位移合成、用 a,b 表示向量 | 6.2.4：`位移`，排除 `数量积/做功` |
| `TB-B2-0032-2` | 6.3 基本定理导入（力的分解），v3 落到 coordinate | 6.3：`分解为两个(力\|向量)` |
| `TB-B2-0039-2` | 6.3.4 数乘坐标，题组是三等分点求坐标，v3 落到概念 | 6.3.4：`三等分点/中点坐标` |
| `TB-B2-0057-1` | 6.4.3 应用举例（例10 测量高度），既有规则只认解三角形模板 | 6.4.3：`仰角/基线/测量高度/目标方向` |
| `TB-B2-0058-1` | 同上（例11 测量角度/方向 + 练习） | 同上 |
| `TB-B2-0071-2` | 6.4.3 下的“数学探究：用向量法研究三角形”，v3 落到概念 | 6.4.3：`由平面向量基本定理/基底` |
| `TB-B2-0087-3` | 7.2 纯算式续块无“计算”触发词 | 7.2：共轭乘积 `(1+i)(1-i)` |
| `TB-B2-0095-1` | 7.3 例4 旋转 120°，既有 7.3 规则只认代数/三角互化；SEC 排 modulus 第一 | 7.3：`复数乘法…几何意义/绕点 O 旋转` |
| `TB-B2-0159-1` | 8.6.2 无 PRI（v6 角规则只挂 section 8.6），v3 落到 perpendicular | 8.6.2：`直线与平面所成的角` |
| `TB-B2-0162-1` | 8.6.2 混合块（例6 棱台体积推导 + 8.6.3 引言），v3 落到 angle | 8.6.2：`棱台的体积` |
| `TB-B2-0211-1` | 9.2 百分位数例题续块；SEC 排 histogram 第一 | 9.2：`百分位数为/第…百分位数` |
| `TB-B2-0222-2` | 9.2.3 方差/标准差练习；SEC 排 sample 第一 | 9.2.3：`方差/标准差` |
| `TB-B2-0233-1` | 9.3 阶梯电价（75% 分档）纯数据块，v3 落到 regression | 9.3：`阶梯电价` |
| `TB-B2-0274-2` | 10.3 独立性假设题；SEC 只有 classical | 10.3：`假设…独立的` |
| `TB-B3-0150-1` | 3.3.2（抛物线节）里的复习参考题第 1 题是椭圆轨道；v3 落到 parabola | 3.3.2：`为一个焦点的椭圆` |
| `TB-B5-0088-2` | 5.2.2 在 SEC_SKIP，牛顿法迭代续块无规则，v3 落到 compute | 5.2.2：`代替` + `零点` |
| `TB-B5-0091-2` | 5.3 在 SEC_SKIP；既有极值/最优化规则都不命中，v3 落到 compute | 5.3：`单调递增/递减` + 排除极值/最值 |

---

## 3. 规则/顺序修正（只追加、不调既有顺序）

### 3.1 为什么不需要改顺序

v6 的两次顺序调整（8.6 角规则前置于宽异面规则、6.4.3 模板前置于余弦规则）解决的是“宽规则先命中抢走目标块”。本批 23 条在 v6 上**全部没有 PRI 命中**（§2.2）——不是被别的 PRI 抢走，而是根本无规则可用（18 条落到 v3_base）或 SEC 候选排序错（5 条）。因此 v7 不需要动任何既有规则的顺序或语义。

新增 22 条规则**一律追加在 `PRIORITY_RULES` 之后**，并加一个 1 行改动让 `Mapper.map()` 遍历 `PRIORITY_RULES + V7_RULES`。因此：

- **v6 由 PRI/CAT/SUM 命中的 300 块，在 v7 上规则与标签 0 变化**（旧规则先命中，新规则不会覆盖它们）；
- 新规则只会接管 v6 的 `v3_base`（37 块）或 `SEC/FILL`（13 块）——因为 PRI 阶段本来就先于 SEC/FILL，这与 v6 既有 PRI 的行为一致；
- 实测 **36 块标签/状态/secondary 变化**（teacher 27 / model 9），另有 **14 块仅 `rule` 溯源字段变化而标签不变**（9 块 `v3_base`→新 PRI、5 块 `SEC`→新 PRI；例如 0157-3/0159-1/0161-1 保持 abstract、0210-1/2 保持 central）。

### 3.2 22 条新规则与命中面

全部规则形如 `(书, 节号, 正条件, 排除词, kp, conf, 备注)`；节号先限定命中面，再用 OCR 稳定的“小节标题/定义句/设问模板/标准题干词”，能少用宽词就少用。

| # | 节 | 规则要点 | 命中 | 命中块（除目标外） |
| ---: | --- | --- | ---: | --- |
| 1 | 3.1 | `解析式为` + 分段公式环境 | 1 | — |
| 2 | 4.5 | 小节标题 `4.5.2 用二分法求方程…近似解` | 1 | — |
| 3 | 4.5.3 | `三个方案/三种方案/增长情况` | 4 | 3 块教师=abstract，标签不变 |
| 4 | 5.2 | `1+tan²` | 1 | — |
| 5 | 5.7 | `消峰平谷` | 1 | — |
| 6 | 6.2.4 | `作图验证/求作向量` | 1 | — |
| 7 | 6.2.4 | `位移` − `数量积/做功` | 2 | model 0029-2（§5.1） |
| 8 | 6.3 | `分解为两个(力\|向量)` | 2 | model 0034-2 |
| 9 | 6.3.4 | `三等分点/中点坐标` | 4 | model 0040-1/0040-2/0044-1 |
| 10 | 6.4.3 | `仰角/基线/测量高度/测量角度/目标方向` − `海伦/秦九韶` | 4 | teacher 0060-2（顺带修正）、model 0056-1 |
| 11 | 6.4.3 | `由平面向量基本定理/基底可以有不同的选` | 1 | — |
| 12 | 7.2 | 共轭乘积 `(1+i)(1-i)` | 1 | — |
| 13 | 7.3 | `复数乘法…几何意义/绕点 O 旋转` | 3 | model 0094-1；teacher 0102-1（教师无 kp 行） |
| 14 | 8.6.2 | `直线与平面所成的角` | 1 | — |
| 15 | 8.6.2 | `棱台的体积` | 2 | model 0161-1 |
| 16 | 9.2 | `百分位数为/第…百分位数` | 3 | 2 块教师=central，标签不变 |
| 17 | 9.2.3 | `方差/标准差` | 15 | teacher 0223-1（顺带修正）+ 13 块标签不变（teacher=central 或已 central 的块） |
| 18 | 9.3 | `阶梯电价` | 1 | — |
| 19 | 10.3 | `假设…独立的` | 1 | — |
| 20 | 3.3.2 | `为一个焦点的椭圆` | 1 | — |
| 21 | 5.2.2 | `代替` + `零点` | 1 | — |
| 22 | 5.3 | `单调递增/递减` − `极值/最值/容积/利润/单调区间` | 10 | teacher 0091-2（目标）、0090-3（顺带修正）；model 0090-2；其余 7 块标签不变 |

### 3.3 收窄过程（第一轮 4 条 harmed → 收窄后 0）

第一版规则更宽，评估发现 4 条 harmed，逐条收窄后清零：

| 原规则 | harmed | 收窄方式 |
| --- | --- | --- |
| 3.1 裸 `\left\{\begin{array}` | 0073-3、0080-1（教师=concept，仅含分段公式） | 加 `解析式为` 引导语，先排除“只有分段公式没有引导语”的题组 |
| 4.5 `用二分法求方程…近似解` | 无 harmed，但会误改 model 0153-1（例2 正文出现同句） | 限定为**小节标题** `4.5.2 …` |
| 9.2 裸 `百分位数` | 0209-1（小节标题“总体百分位数的估计”，教师=histogram） | 要求 `百分位数为/分别/约为` 或 `第…百分位数` |
| 10.3 裸 `是独立的/相互独立` | 0273-2（复习题“事件A与B相互独立吗”，教师=classical） | 改为 `假设…独立的` 独立性假设句式 |

> 收窄后 671 model 行变化从 10 条降到 **9 条**，且 9 条全部有同节教师目标作为“同规则依据”；未引入任何 block_id 硬编码（规则只含书/节号/正则/排除词）。

---

## 4. 评估（1026 条 / 四个子集）

### 4.1 主指标（exact / module；any 与 exact 同值）

| 子集 | 分母 | v3 | v4 | v5 | v6 | **v7** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 360 | 327 | 253 / 308 | 327 / 327 | 327 / 327 | 327 / 327 | **327 / 327** |
| 288 | 270 | 200 / 258 | 229 / 262 | 234 / 262 | 235 / 262 | **238 / 263** |
| 310 | 273 | 226 / 267 | 265 / 270 | 265 / 270 | 273 / 273 | **273 / 273** |
| 第四批 round4 | 156 | 112 / 149 | 133 / 154 | 133 / 154 | 133 / 154 | **156 / 156** |
| **合计** | **1026** | **791 / 982** | **954 / 1013** | **959 / 1013** | **968 / 1016** | **994 / 1019** |

- **口径 A（仅 23 条目标）**：327 + 235 + 273 + 156 = **991/1026**，module **1018/1026**。
- **口径 B（实际运行，含 3 条同规则顺带修正）**：**994/1026**，module **1019/1026**。
- `any`（含 secondary）= exact（本批校正块均无跨模块 secondary），四个子集均与 exact 同值。

### 4.2 目标修复与 harmed

- 23 条目标 `fixed` = **23/23**；`harmed` = **0**；`still_wrong` = **32**（全部是 288 批的 v6 遗留，本任务边界不处理；见 §4.4）。
- v6 历史 8 条目标（第三批）在 v7 上仍全部命中教师标签：**8/8**（v7 未回退）。

### 4.3 反样本守卫（27/27）

每条新规则/每组相似字面都配了至少 1 条“教师已对、且含相似字面”的反向样本，逐块核对 v7 未改错：

- 3.1：0073-3、0080-1（含分段公式但无“解析式为”，保持 concept）；0075-1（既有“分段”规则仍先命中）；
- 4.5：0153-1（例2 正文含“用二分法求方程的近似解”但不是小节标题，保持 logarithm）；
- 4.5.3：0157-3、0159-1（标签不变）、0162-2（浮萍仍 exponential）；
- 5.2：0186-1（定义证明 `sinα=y/r` 不被同角规则抢走）；
- 5.7：0254-1（潮汐演算块不含“消峰平谷”，保持 graph）；
- 6.2.4：0024-1（数量积定义块含“位移”但被排除词挡住）；
- 6.3：0032-1（coordinate）、0033-1（decompose）；
- 6.4.3：0060-1/0068-1（cosine，模板规则优先）、0062-1（海伦/秦九韶被排除词挡住）、0070-1（数学探究导语保持原标签）；
- 7.2：0085-2（modulus 不被 `(1+i)(1-i)` 形式误伤）；
- 7.3：0091-2（既有三角表示规则先命中 geometric）；
- 8.6.2：0158-1（perpendicular）、0163-1（angle）；
- 9.2：0209-1（小节标题块保持 histogram）；9.2.3：0219-1（central）；10.3：0273-2（classical）；
- 5.2.2：0087-3、0088-1（无“代替”，保持 compute/tangent）；5.3：0103-1（既有极值规则先命中）、0100-3（compute）。

### 4.4 遗留（不在本任务范围）

`still_wrong` 32 条**全部在 288 批**（360 / 310 / 第四批各有 0 条）：3.4 分段应用、5.7 三角应用、6.4.3 解三角形应用、8.6.2 线面垂直等。这是 v5/v6 已披露的遗留项，v7 按任务边界**没有**为它们扩规则，避免把未复核面打开。

---

## 5. mapped / reviewed 产物与一致性

### 5.1 `mapped_1797_v7.json`

- 覆盖 **1797/1797**，block_id 唯一 **1797**；`model_version=textbook-map-v7-2026-11-07`；
- status（映射阶段）：mapped **1747** / non_content **43** / vocab_gap **7**（与 v6 完全一致）；
- 规则命中：`v3_base` 1182、`SEC` 249、`PRI` 343、`FILL` 16、`CAT` 5、`SUM` 2；
- v6→v7 变化 **36** 块（teacher 27 / model 9）标签/状态/secondary 变化，全部由 22 条新规则接管；另有 **14 块仅 `rule` 字段变化**（标签不变）；v6 由 PRI/CAT/SUM 命中的 300 块规则与标签完全不变。

### 5.2 `mapped_1797_reviewed_v7.json`

- count **1797**；teacher **1126** / model **671**；
- **teacher 1126 行与 `mapped_1797_reviewed_round4.json` 逐字段 0 差异**（原样复制，含 `teacher_version`）；
- teacher_version 逐行保留：360=`textbook-review-2026-11-06`、288=`textbook-review-v4-round2-2026-11-06`、310=`textbook-review-v5-round3-2026-11-07`、第四批=`textbook-review-v6-round4-2026-11-07`；
- model 671 行全部取自 v7 映射（kp/status/secondary/confidence/reason/version）；
- status（reviewed 口径）：mapped **1702** / non_content **84** / vocab_gap **11**（与 round4 一致）。

### 5.3 teacher 行变化 27 条（mapped 层，不影响 reviewed 教师标签）

| 类别 | 条数 | 说明 |
| --- | ---: | --- |
| 23 条第四批目标 | 23 | reviewed 中教师标签本已正确，只有模型侧标签修正 |
| 同规则顺带修正的教师错块 | 3 | `TB-B2-0060-2`（apply）、`TB-B2-0223-1`（central）、`TB-B5-0090-3`（monotonic）——教师标签与 v7 一致，是净收益 |
| 教师只给模块/无 kp 的 teacher 行 | 1 | `TB-B2-0102-1`：教师无 kp（reviewed 原样保留），仅 mapped 层模型标签 concept→geometric |

---

## 6. 671 model 行变化审计（未经教师验证的 9 条）

### 6.1 变化清单

| block_id | v6 | v7 | 规则依据 / 语义核对 |
| --- | --- | --- | --- |
| `TB-B2-0029-2-p0029-02` | `05_03_dot` | **`05_01_concept`** | 习题6.2 位移合成题（“两次位移的合成”）；v6 无数量积证据，属向量线性运算 |
| `TB-B2-0034-2-p0034-02` | `05_02_coordinate` | **`05_06_decompose`** | 习题6.3 用 a,b 基底表示向量（用基底表示 CD/CE）；无坐标运算证据 |
| `TB-B2-0040-1-p0040-01` | `05_01_concept` | **`05_02_coordinate`** | 例题续块：三等分点坐标公式推导 |
| `TB-B2-0040-2-p0040-02` | `05_01_concept` | **`05_02_coordinate`** | 习题：线段 AB 三等分点求坐标 |
| `TB-B2-0044-1-p0044-01` | `05_01_concept` | **`05_02_coordinate`** | 综合运用：平行四边形三等分点 + 坐标 |
| `TB-B2-0056-1-p0056-01` | `05_01_concept` | **`04_11_apply`** | 6.4.3 例9 测量河对岸两点距离（基线/测量方案） |
| `TB-B2-0094-1-p0094-01` | `06_03_modulus` | **`06_04_geometric`** | 7.3.2 复数乘除三角表示及其几何意义 |
| `TB-B2-0161-1-p0161-01` | `08_08_distance` | **`08_02_area_volume`** | 8.6.2 例5/例6（例6 推导棱台体积公式），与 0162-1 教师标签同向 |
| `TB-B5-0090-2-p0090-02` | `03_02_tangent` | **`03_03_monotonic`** | 5.3.1 导数正负与函数单调性（h′(t)<0 ⇒ 单调递减） |

### 6.2 审计结论

- 9/671 = **1.3%**；每条都能指到“同节教师目标”所用规则：0029-2/0030-4 共用位移规则、0034-2 与 0032-2 共用分解规则、0040-*/0044-1 与 0039-2 共用三等分点规则、0056-1 与 0057-1/0058-1 共用测量规则、0094-1 与 0095-1 共用旋转规则、0161-1 与 0162-1 共用棱台体积规则、0090-2 与 0090-3/0091-2 共用单调性规则。
- 9 条的方向均是“去掉一个无正文证据的错标，改为该块实际主考”，没有出现“同一规则把大量 model 行整体搬家”的系统性风险；规则最宽的是 9.2.3 `方差/标准差`（命中 15 块），但其中 13 块 v6 已是 central、仅 rule 字段变化，只有 1 条 teacher 顺带修正，model 行 0 变化。
- 因此不需要回退任何规则。**这些变化仍是未经教师验证的**：若下一轮抽样覆盖这些块，应以教师标签为准（可能推翻其中某条）。

---

## 7. PG（`textbook_block_annotations`）

命令（`.venv\Scripts\python.exe`；先 dry-run 后 `--apply`）：

```powershell
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v7.json --model-version textbook-map-v7-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v7_2026-11-07.json           # dry-run
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v7.json --model-version textbook-map-v7-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v7_2026-11-07.json --apply
```

| 校验项 | 结果 |
| --- | --- |
| dry-run 待写/变更 | **671**（全部 model 行：model_version v6→v7；其中 9 条标签一并更新） |
| apply 写入 | 新建 **0** / 更新 **671** / 未变 **1126** |
| active / unique chunk | **1797 / 1797** |
| classification_source | teacher **1126** / model **671** |
| status | mapped **1702** / non_content **84** / vocab_gap **11** |
| model 行 model_version | `textbook-map-v7-2026-11-07` × **671**（非 v7 = 0） |
| teacher 行版本 | 360/288/310/168 四版逐行保留（版本不符 0） |
| teacher 行与写入前备份逐字段差异 | **0** |
| teacher 行 vs reviewed_v7 教师标签（kp/status/source/version/review_status）差异 | **0** |
| model 行与 reviewed_v7 期望字段差异 | **0**；model 标签变化 **9**（与 §6.1 一致） |
| DB status vs reviewed_v7 status 差异 | **0** |
| `knowledge_annotations` active | **9092**（gaokao_paper 8007 / mock_exam 1085，未变） |
| RLS / policies / indexes | (True, True) / `pol_textbook_block_annotations_owner` / 3 个索引（与 v6 一致） |
| 幂等（apply 后重复 dry-run） | 待写/变更 **0** |
| `tools/check_all.py --quiet` | **17/17** |
| 写入前备份 | `var/textbook_mapping/backup_pg_draft_before_v7_2026-11-07.json` |

---

## 8. Obsidian vault（仅 textbook）

前后命令（`$env:PYTHONIOENCODING='utf-8'`；先 dry-run 后 `--apply`；写前备份 5 册）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe tools\project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated          # dry-run
.venv\Scripts\python.exe tools\project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated --apply
.venv\Scripts\python.exe var\vault_backup\verify_textbook_links.py --vault "<vault 路径>" --backup-dir "D:\Chilon\var\vault_backup\textbooks_before_links_2026-11-06"
```

| 校验项 | 结果 |
| --- | --- |
| 写前备份 | `var/vault_backup/textbooks_before_v7_2026-11-07/`（5 册，相对 `03_Textbooks/**` 保留路径 + sha256 记录） |
| dry-run 计划 | write=**2** / unchanged=**3** |
| apply 写入 | 新写 **2** 个文件（必修第二册、选择性必修第二册）/ 幂等不变 **3** / 跳过 0 |
| 块级链接 | **1702**（teacher **1031** / model **671**）；vocab_gap 待补 **11**；non_content **84**；无标注 0；缺主标注 0 |
| 与 PG 对比 | PG active teacher 1031 / model 671 / vocab_gap 11 / non_content 84 —— **完全一致** |
| 链接目标 | 83 个不同 kp_id、1702 次；缺失笔记 **0**、缺别名 **0** |
| 原文删链接行后与基线（`textbooks_before_links_2026-11-06`）比对 | 5 册均 **0 差异** |
| 与 v7 前备份比对（去链接行 + 去时间戳） | 5 册均 **0 差异**；链接行 1704 行相同 / **9 行变化**（恰为 §6.1 的 9 条 model 行，目标 kp 与 PG 一致）；3 册逐字节不变，2 册仅链接行变化 |
| 无标注表回落模拟 | 链接行 0，输出与原文基线一致 **5/5** |
| mock 投影回归 | 998 文件与 vault 一致 998，差异 **0** |
| 二次 dry-run | write=**0** / unchanged=**5**（0 变更） |
| 高考卡 | 6324 张聚合 sha256 **未变**（apply 日志 `✅ 未变`） |
| `verify_textbook_links.py` | **PASS**（格式/每页计数/primary 顺序/secondary/幂等/回落全部通过） |

为什么本次不是“写 0 文件”：23 条目标块都是 teacher 行，教师标签在 PG 里本来就对、不进 vault 渲染变化；但 22 条新规则顺带改了 **9 条 model 行**，model 链接会渲染，因此 2 册（含这些块的必修第二册 / 选择性必修第二册）各变化 8/1 条链接行，其余 3 册幂等不变。链接总数不变（1702），只是 9 行链接的目标 kp 变了。

---

## 9. in-sample 与 fresh holdout 局限（必须与数字一起读）

1. **本轮没有 fresh holdout。** 第四批 168 块（含 23 条目标）在本轮已进入已标注集：它们的教师标签直接参与了规则设计，**第四批 156/156 是 in-sample 自证**，不能当作泛化证据。
2. **剩余 671 model 无教师标签，不能当 holdout。** 本轮只对它们在 v7 下的 9 条变化做了“规则依据 + 语义方向”的逐条审计（§6），并没有教师复核；它们既不构成验证集，也不能支撑“v7 在未标注块上也更准”的结论。
3. **in-sample 修复评价仍有意义，但只用于“规则收敛”：** 说明 22 条窄规则能在不伤害 968 条既有正确标签的前提下修好 23 条已知错误；**真实准确率仍需新一轮随机抽样**（建议从 671 model 里抽 fresh 样本，抽样前不参与任何规则设计）。
4. **规则与评估同源偏差仍在：** 本版规则是看着 23 条错因写的，`harmed=0` 只保证“没有在 1026 条教师标签上翻车”，不保证未复核面不误伤；已用逐规则命中面 + 27 条反样本守卫把风险面压到最小，但规则仍依赖字面特征。
5. **窄条件规则天然欠泛化：** 本批大量使用小节标题/定义句/标准题干词（`4.5.2 用二分法求方程…`、`1+tan²`、`消峰平谷`、`(1+i)(1-i)`、`假设…独立的`）；OCR 变体/同义表述（如“用二分法求方程的根”“峰谷电价”）可能漏命中。若后续复核发现同类块，应继续用“节号 + 窄条件”扩规则，而不是放宽阈值。
6. **教师标签口径问题：** 个别块的教师标签与词表语义不完全一致（如 `TB-B2-0162-1` 混合块主考体积、`TB-B3-0150-1` 抛物线节下的椭圆复习题）；v7 按教师口径执行并在 §2 备注，不擅自改口径。
7. **未改口径与产物：** 未改 v3–v6、未改教师标签、未改 design master/README/review_sheets/抽样工具、未 commit、未跑 alembic。

---

## 10. 产物与复现

| 产物 | 说明 |
| --- | --- |
| `tools/kb_textbook_map_v7.py` | v7 规则引擎（v6 复制；追加 22 条窄 PRI 规则；`--stage map` / `--stage eval`） |
| `var/textbook_mapping/mapped_1797_v7.json` | 全量 1797 映射（`model_version=textbook-map-v7-2026-11-07`，`rule` 溯源） |
| `var/textbook_mapping/mapped_1797_v7_batch.txt` | 1797 行批次文本 |
| `var/textbook_mapping/mapped_1797_v7_eval.json` | 本报告数字的机器可读来源（metrics / target_check / v6_target_check / guard / changes / model_row_changes / checks） |
| `var/textbook_mapping/mapped_1797_reviewed_v7.json` | 应用 1126 教师标签后的 reviewed（teacher 行与 round4 **逐字段 0 差异**；model 671 行用 v7） |
| `var/textbook_mapping/backup_pg_draft_before_v7_2026-11-07.json` | PG 写入前备份 |
| `var/vault_backup/textbooks_before_v7_2026-11-07/` | vault 5 册写入前备份 |
| `var/projection/report.md` / `var/projection/manifest.json` | 投影工具报告/manifest（本次运行覆盖） |

复现：

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\kb_textbook_map_v7.py --stage map
python tools\kb_textbook_map_v7.py --stage eval
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var\textbook_mapping\mapped_1797_reviewed_v7.json --model-version textbook-map-v7-2026-11-07 --backup var\textbook_mapping\backup_pg_draft_before_v7_2026-11-07.json
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var\textbook_mapping\mapped_1797_reviewed_v7.json --model-version textbook-map-v7-2026-11-07 --backup var\textbook_mapping\backup_pg_draft_before_v7_2026-11-07.json --apply
.venv\Scripts\python.exe tools\project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated --apply
python tools\check_all.py --quiet    # 17/17
```

自检：

| 检查 | 结果 |
| --- | --- |
| mapped 覆盖 / 唯一 block_id | 1797 / 1797 |
| v6→v7 变化块 | **36**（teacher 27 / model 9） |
| 23 条目标修复 | **23/23** |
| 新 harmed | **0** |
| 360 / 288 / 310 / 第四批 exact | **327/327、238/270、273/273、156/156** |
| 合计 exact | **968→994/1026**（仅 23 目标口径 **991/1026**） |
| 合计 module | **1016→1019/1026**（仅 23 目标口径 **1018/1026**） |
| v6 历史 8 条目标保持 | 8/8 |
| 反样本守卫 | 27/27 |
| reviewed_v7 teacher 行逐字段差异 | 0（1126 行） |
| teacher_version 保留 | 360 / 288 / 310 / 168 四版逐行不变 |
| model 行标签变化 | 9（全部审计，见 §6） |
| `tools/check_all.py --quiet` | 17/17 |

---

> 已写入 PG：`mapped_1797_reviewed_v7.json` → `textbook_block_annotations`（更新 671 个 model 行 / teacher 1126 行不变；备份 `backup_pg_draft_before_v7_2026-11-07.json`）；
> vault 重投影写 2 册（8+1 条 model 链接目标变化）、链接面 1702（teacher 1031 / model 671）+ 11 待补；幂等 0。
> **第四批已 in-sample + 671 model 无教师标签 → 本轮没有 fresh holdout，994/1026 不能外推。**

