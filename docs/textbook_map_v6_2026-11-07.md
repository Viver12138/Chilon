---
type: report
title: 教材映射 v6：第三批 8 条不一致修正 + 全量重跑与 PG/vault 校验
updated: 2026-11-07
status: v6-applied
model_version: textbook-map-v6-2026-11-07
---

# 教材映射 v6：第三批 8 条不一致修正 + 全量重跑与 PG/vault 校验

> 输入：`mapped_1797_v5.json`（v5 基线）、`blocks_1797_with_structure.json`、`structure_5books.json`、`corpus/eval/kp_vocab.md`。
> 映射阶段（`--stage map`）**不读取教师标签**；教师标签只在评估阶段（`--stage eval`）读取，来源为
> `review_360_parsed.json`（360）、`review_round2_parsed.json`（288）、`review_round3_parsed.json`（310），合计 **958 条**，评估分母 **870**。
> 未改 `kb_textbook_map_v3.py` / `v4` / `v5`；未改 `SECTION_KP` / `SEC_SKIP` / 阈值 / 既有规则；未调 OCR；未 commit。

## 0. 结论先行

- **第三批复核暴露的 8 条不一致 8/8 全部修好**：8 条在 958 教师标签上由错转对，**新 harmed = 0**。
- 第三批 310 完整标签 exact **265/273 → 273/273**；360 保持 **327/327**；288 **234/270 → 235/270**（+1 见 §4 的 0100-2 顺带修正）。
  合计 exact **826/870 → 835/870（94.9% → 96.0%）**；若只计任务 8 条目标、不把 0100-2 计入，则为 **834/870，与期望一致**。模块命中 **859 → 862**。
- 修法**全部是规则层**：新增 8 条窄条件 PRI 规则 + 2 处规则顺序调整（8.6 角定义前置于宽“异面”规则；6.4.3 解三角形模板前置于既有余弦规则）；**没有硬编码 block_id**，既有规则/排除词一律不动。
- 全量 1797 中 v5→v6 **只有 9 块**变化（8 条目标 + 1 条同规则同模式顺带修正的 0100-2，逐条解释见 §4），**全部是 teacher 行；839 个 model 行标签变化 0**（因此 PG 只改 model_version）。
- PG：dry-run 待写 **839**（全部 model 行）；apply 后新建 0 / 更新 839 / 未变 958，active **1797**，teacher **958** / model **839**，status **1714/74/9**，`knowledge_annotations` **9092 未变**，幂等 dry-run **0**。
- vault：重投影 **写 0 文件 / 幂等不变 5**；块级链接 **1714**（teacher 875 / model 839）+ vocab_gap 待补 9；**原文 0 差异、missing 0**，`verify_textbook_links.py` PASS。
- `tools/check_all.py --quiet` **17/17**。

## 1. 规则层诊断：这 8 条分别错在哪一层

先按“命中层”拆解 v5 的错因（`rule` 字段 + 逐块复算 PRI/SEC 命中面）。8 条中 **6 条是“规则缺位/过窄导致的 v3_base 或 SEC 误选”，2 条是“既有规则层问题”**：

| # | block_id | 节 | 教师标签 | v5 标签 | v5 命中层 | 根因 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `TB-B1-0101-1-p0101-01` | 3.4 函数的应用 | `kp_02_13_segment` | `kp_02_01_concept` | `v3_base` | 3.4 节 PRI 只认“函数模型/个税/应纳税”，而个税例题的**公式续写块**只有“当…时，所以 y=…；”分段公式，无建模词，落 v3 的“函数概念” |
| 2 | `TB-B1-0155-2-p0155-02` | 4.5.3 函数模型的应用 | `kp_02_12_abstract` | `kp_02_09_logarithm` | `v3_base` | 4.5.3 无“统计数据/人口数据拟合”规则；v3 按“人口”字面归对数 |
| 3 | `TB-B1-0162-1-p0162-01` | 4.5.3 函数模型的应用 | `kp_02_11_zero` | `kp_02_12_abstract` | `v3_base` | “习题4.5 复习巩固”里的二分法/零点题组无定理/模型词，落 v3 的 abstract |
| 4 | `TB-B1-0254-2-p0254-02` | 5.7 三角函数的应用 | `kp_04_11_apply` | **∅（vocab_gap）** | `v3_base` | 5.7 不在 `SECTION_KP`，也无 PRI 规则；该块只有一句应用结论（进/出港），v3 空标签，FILL 无候选可填 |
| 5 | `TB-B2-0061-3-p0061-03` | 6.4.3 余弦定理、正弦定理 | `kp_04_09_cosine` | `kp_05_01_concept` | `v3_base` | 块末“测量的实习作业”被既有余弦规则的排除词“测量”挡住，且不含“解这个三角形/分别根据…”模板句 |
| 6 | `TB-B2-0068-1-p0068-01` | 6.4.3 余弦定理、正弦定理 | `kp_04_09_cosine` | `kp_05_01_concept` | `v3_base`（**PRI 主条件命中但被 neg 误杀**） | 正文含“分别根据下列条件解三角形”，本应命中余弦规则；但同一块第 12 题是航行应用题（含“**航行**”），被该规则排除词误杀，回落 v3 基线 |
| 7 | `TB-B2-0154-1-p0154-01` | 8.6 空间直线、平面的垂直 | `kp_08_06_angle` | `kp_08_03_position` | `PRI:8.6 节内异面直线位置关系` | 宽的“8.6 异面→位置关系”规则**先于**角定义规则命中（v5 规则表顺序），把“异面直线所成角”定义块抢成 position |
| 8 | `TB-B5-0064-1-p0064-01` | 5.1 导数的概念及其意义 | `kp_03_08_concept` | `kp_03_03_monotonic` | `SEC:section_elect` | PRI 5.1 只认“平均/瞬时变化率”，导语块只有“变化率问题”标题，不命中；SEC 按正文“函数的单调性”旧知识重选（正文分 6.0 > 节先验 5.0），落到 monotonic |

结论：**主因不是 `neg` 误杀（仅 0068-1 是），而是“窄条件规则缺位 + 规则顺序/优先级不匹配”**。因此 v6 的修法是给每个错因补一条“节号 + 正文特征”的窄 PRI 规则，并把更具体的规则放到更宽的规则之前；对 0068-1 保留原规则与排除词不动，靠**更具体的模板句规则**绕开误杀，避免放宽既有排除词造成新的误伤面。

## 2. 修法：8 条窄条件规则 + 2 处顺序调整（无 block_id 硬编码）

v6 = v5 引擎（CAT/SUM/PRI/SEC/FILL 结构、`SECTION_KP`、`SEC_SKIP`、阈值、既有规则全部不动）+ 以下新增规则：

| # | 规则（PRI，节号 + 正文特征） | 目标 | 置信 | 命中面（全量 1797） |
| --- | --- | --- | ---: | --- |
| 1 | 必修一 3.4：`当[^。]{0,80}时[，,]?[^。]{0,80}y\s*=[^。]{0,60}[；;]` → `kp_02_13_segment`，**置于 3.4 函数建模规则之后** | 0101-1（+ 0100-2） | 0.66 | 3 块：0100-1（先命中建模→abstract，不受影响）、0100-2、0101-1 |
| 2 | 必修一 4.5.3：`国家统计局\|人口总数` → `kp_02_12_abstract` | 0155-2 | 0.66 | 3 块：0155-1/0155-2/0156-1（后两块本来即 abstract，只改 rule 字段） |
| 3 | 必修一 4.5.3：`二分法[^。]{0,20}零点` → `kp_02_11_zero` | 0162-1 | 0.68 | 1 块（故意不用裸“二分法/零点”：那会命中 0162-2 浮萍块与 0167-2 等未复核块） |
| 4 | 必修一 5.7：`在港口停留\|港口停留` → `kp_04_11_apply` | 0254-2 | 0.64 | 1 块（不用宽“进港/出港/港口”：0254-1 的演算正文也含进/出港） |
| 5 | 必修二 6.4.3：`分别根据下列条件解三角形`，排除 `游泳\|水流\|测量\|塔高\|台风\|小结\|本章知识结构` → `kp_04_09_cosine`，**置于既有余弦规则之前** | 0068-1 | 0.70 | 2 块：0060-1（本来就是 cosine）、0068-1 |
| 6 | 必修二 6.4.3：`内角\s*A\s*[，,]\s*B\s*[，,]\s*C\s*的对边` → `kp_04_09_cosine` | 0061-3 | 0.68 | 1 块 |
| 7 | 必修二 8.6：`叫做异面直线` → `kp_08_06_angle`，**置于宽“8.6 异面→位置关系”规则之前** | 0154-1 | 0.68 | 1 块（0153-1/0155-1/0155-2 不含定义句，仍走宽规则→position） |
| 8 | 选必二 5.1：`导数的概念及其意义\|5\.1\.1` → `kp_03_08_concept` | 0064-1 | 0.66 | 1 块（0069-1 是“5.1.2 …及其几何意义”，不命中，保持 tangent） |

顺序调整的作用：
- **0068-1** 不修改既有余弦规则（其 `neg` 里的“航行”对其它块仍有效），新增的模板句规则更具体、排除词保留“游泳/水流/测量/塔高/台风”，只把“航行”从这一更具体规则的排除面里移除 → 误杀面被限制在“模板句”这一强正条件下；
- **0154-1** 不修改宽“异面”规则（0153-1/0155-1/0155-2 教师=position 的守卫仍然生效），只把“异面直线所成角定义句”规则前移；
- 规则 1 必须置于 3.4 函数建模规则之后：0100-1（教师=abstract）同时含“个税/应纳税”与“当…时”，建模规则先命中即可保持 abstract。

## 3. 8 条不一致：before / after（v3 / v4 / v5 / v6）

| # | block_id | 节 | 教师标签 | v3 | v4 | v5（错） | **v6** | v6 命中规则 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `TB-B1-0101-1-p0101-01` | 3.4 | `kp_02_13_segment` | `kp_02_01_concept` | `kp_02_01_concept` | `kp_02_01_concept` | **`kp_02_13_segment`** ✅ | `PRI:3.4 节内分段函数公式续写` |
| 2 | `TB-B1-0155-2-p0155-02` | 4.5.3 | `kp_02_12_abstract` | `kp_02_09_logarithm` | `kp_02_09_logarithm` | `kp_02_09_logarithm` | **`kp_02_12_abstract`** ✅ | `PRI:4.5.3 节内统计/人口数据建模` |
| 3 | `TB-B1-0162-1-p0162-01` | 4.5.3 | `kp_02_11_zero` | `kp_02_12_abstract` | `kp_02_12_abstract` | `kp_02_12_abstract` | **`kp_02_11_zero`** ✅ | `PRI:4.5.3 节内二分法求零点习题` |
| 4 | `TB-B1-0254-2-p0254-02` | 5.7 | `kp_04_11_apply` | ∅（vocab_gap） | ∅（vocab_gap） | ∅（vocab_gap） | **`kp_04_11_apply`**（mapped）✅ | `PRI:5.7 节内港口潮汐应用结论` |
| 5 | `TB-B2-0061-3-p0061-03` | 6.4.3 | `kp_04_09_cosine` | `kp_05_01_concept` | `kp_05_01_concept` | `kp_05_01_concept` | **`kp_04_09_cosine`** ✅ | `PRI:6.4.3 节内解三角形（三内角对边设问）` |
| 6 | `TB-B2-0068-1-p0068-01` | 6.4.3 | `kp_04_09_cosine` | `kp_05_01_concept` | `kp_05_01_concept` | `kp_05_01_concept` | **`kp_04_09_cosine`** ✅ | `PRI:6.4.3 节内解三角形模板（分别根据下列条件）` |
| 7 | `TB-B2-0154-1-p0154-01` | 8.6 | `kp_08_06_angle` | `kp_08_03_position` | `kp_08_03_position` | `kp_08_03_position` | **`kp_08_06_angle`** ✅ | `PRI:8.6 节内异面直线所成角定义` |
| 8 | `TB-B5-0064-1-p0064-01` | 5.1 | `kp_03_08_concept` | `kp_03_03_monotonic` | `kp_03_03_monotonic` | `kp_03_03_monotonic` | **`kp_03_08_concept`** ✅ | `PRI:5.1 节导语/变化率问题小节` |

新 harmed = **0**；同规则反向样本守卫 **12/12 保持**（逐条见 §5）。

## 4. 全量变化审计（v5→v6：1797 中仅 9 块）

| # | block_id | 节 | before → after | v6 规则 | 教师标签 | 审计判断 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `TB-B1-0101-1-p0101-01` | 3.4 | `kp_02_01_concept` → `kp_02_13_segment` | 新增 3.4 分段公式 | `kp_02_13_segment` | 目标①修好 |
| 2 | `TB-B1-0155-2-p0155-02` | 4.5.3 | `kp_02_09_logarithm` → `kp_02_12_abstract` | 新增 4.5.3 统计人口 | `kp_02_12_abstract` | 目标②修好 |
| 3 | `TB-B1-0162-1-p0162-01` | 4.5.3 | `kp_02_12_abstract` → `kp_02_11_zero` | 新增 4.5.3 二分零点 | `kp_02_11_zero` | 目标③修好 |
| 4 | `TB-B1-0254-2-p0254-02` | 5.7 | ∅（vocab_gap）→ `kp_04_11_apply`（mapped） | 新增 5.7 港口结论 | `kp_04_11_apply` | 目标④修好（状态 vocab_gap→mapped） |
| 5 | `TB-B2-0061-3-p0061-03` | 6.4.3 | `kp_05_01_concept` → `kp_04_09_cosine` | 新增 6.4.3 三内角对边 | `kp_04_09_cosine` | 目标⑤修好 |
| 6 | `TB-B2-0068-1-p0068-01` | 6.4.3 | `kp_05_01_concept` → `kp_04_09_cosine` | 新增 6.4.3 模板（neg 收窄） | `kp_04_09_cosine` | 目标⑥修好 |
| 7 | `TB-B2-0154-1-p0154-01` | 8.6 | `kp_08_03_position` → `kp_08_06_angle` | 新增 8.6 角定义（前置） | `kp_08_06_angle` | 目标⑦修好 |
| 8 | `TB-B5-0064-1-p0064-01` | 5.1 | `kp_03_03_monotonic` → `kp_03_08_concept` | 新增 5.1 节导语 | `kp_03_08_concept` | 目标⑧修好 |
| 9 | `TB-B1-0100-2-p0100-02` | 3.4 | `kp_02_01_concept` → `kp_02_13_segment` | 新增 3.4 分段公式（同规则） | `kp_02_13_segment` | **顺带修正**（见下） |

第 9 块说明（逐条解释）：`0100-2` 与 `0101-1` 是同一个“个税阶梯公式”例题的连续续写块，正文结构完全相同（都是“当…时，所以 y=…；”），任何语义规则都无法只命中后者；它是 **288 第二批的历史错块**（v5 文档 §7.3 已把“3.4 分段函数”列为剩余 36 条遗留项之一），v6 的分段规则一并把它修对。这是净收益、不隐藏；它使 288 子集 exact 234→**235**、全量 exact 826→**835**。若严格只认任务 8 条目标（不算此块），则 288 保持 234、合计 **834/870**，与期望一致。

- 变化块 **全部是 teacher 行**（9/9）；**839 个 model 行 kp/status/secondary 变化 = 0**（v6 没有触及任何 model 块）。
- `rule` 命中分布：v3_base 1219 / PRI **293**（v5 为 283）/ SEC 262 / FILL 16 / CAT 5 / SUM 2；基线未命中块与 v3 逐块一致（差异 **0**）。
- 模型标签状态（未叠加教师）：mapped **1747** / non_content 43 / vocab_gap **7**（v5 为 1746/43/8；唯一状态迁移即 0254-2 vocab_gap→mapped）。

## 5. 反样本守卫（12/12 保持）

| block_id | 守护点 | v5 | v6 | 保持 |
| --- | --- | --- | --- | --- |
| `TB-B1-0100-1-p0100-01` | 3.4 题头含“个税/应纳税”，仍需 abstract（建模规则先命中） | `kp_02_12_abstract` | `kp_02_12_abstract` | ✅ |
| `TB-B1-0155-1-p0155-01` | 4.5.3 统计规则命中但标签不变 | `kp_02_12_abstract` | `kp_02_12_abstract` | ✅ |
| `TB-B1-0156-1-p0156-01` | 同上 | `kp_02_12_abstract` | `kp_02_12_abstract` | ✅ |
| `TB-B1-0162-2-p0162-02` | 浮萍 y=a^t 仍命中指数规则，不被零点规则抢走 | `kp_02_08_exponential` | `kp_02_08_exponential` | ✅ |
| `TB-B1-0167-2-p0167-02` | 未复核块含宽“二分法”，窄短语规则不命中 | `kp_02_12_abstract` | `kp_02_12_abstract` | ✅ |
| `TB-B1-0254-1-p0254-01` | 含进/出港演算但不含“港口停留”，不受 5.7 规则影响 | `kp_04_05_graph` | `kp_04_05_graph` | ✅ |
| `TB-B2-0059-2-p0059-02` | 含游泳/水流，被模板规则排除词拦住 | `kp_05_01_concept` | `kp_05_01_concept` | ✅ |
| `TB-B2-0060-1-p0060-01` | “分别根据下列条件”块保持 cosine | `kp_04_09_cosine` | `kp_04_09_cosine` | ✅ |
| `TB-B2-0153-1-p0153-01` | 8.6 节导语不含“叫做异面直线”，仍走宽异面规则 | `kp_08_03_position` | `kp_08_03_position` | ✅ |
| `TB-B2-0155-1-p0155-01` | 8.6 习题集不含定义句 | `kp_08_03_position` | `kp_08_03_position` | ✅ |
| `TB-B2-0155-2-p0155-02` | 8.6 习题块不含定义句 | `kp_08_03_position` | `kp_08_03_position` | ✅ |
| `TB-B5-0069-1-p0069-01` | 5.1.2 导数概念块（非节导语）不受 5.1 新规则影响 | `kp_03_02_tangent` | `kp_03_02_tangent` | ✅ |

## 6. 958 教师标签指标（三批合计，分母 870）

分母口径：教师给了 `kp_*` 标签，且该块 `model_status != non_content`。360 分母 **327**、288 分母 **270**、310 分母 **273**，合计 **870**（教师标签 958 条）。

| 子集 | 分母 | 版本 | module | exact | any |
| --- | ---: | --- | ---: | ---: | ---: |
| 360（第一批） | 327 | v3 | 308 | 253 | 253 |
| 360 | 327 | v4 | 327 | 327 | 327 |
| 360 | 327 | v5 | 327 | 327 | 327 |
| 360 | 327 | **v6** | **327** | **327** | **327** |
| 288（第二批） | 270 | v3 | 258 | 200 | 200 |
| 288 | 270 | v4 | 262 | 229 | 229 |
| 288 | 270 | v5 | 262 | 234 | 234 |
| 288 | 270 | **v6** | 262 | **235** | **235** |
| 310（第三批） | 273 | v3 | 267 | 226 | 226 |
| 310 | 273 | v4 | 270 | 265 | 265 |
| 310 | 273 | v5 | 270 | 265 | 265 |
| 310 | 273 | **v6** | **273** | **273** | **273** |
| 合计 | 870 | v3 | 833 | 679 | 679 |
| 合计 | 870 | v4 | 859 | 821 | 821 |
| 合计 | 870 | v5 | 859 | 826 | 826 |
| 合计 | 870 | **v6** | **862** | **835** | **835** |

- v5→v6 在 870 上 **fixed 9 / harmed 0 / still_wrong 35**；8 条目标口径为 fixed 8 / harmed 0，**exact 826→834**；把 0100-2 也算入后为 **835**（§4）。
- 剩余 35 条仍错的块**全部在 288 第二批**，例如 3.4 分段应用、5.7 三角应用复习题、6.4.3 解三角形应用、8.6.2 线面垂直等；v6 按任务边界**未扩规则处理它们**，避免把未复核面打开。
- 模块命中 859→862 的 +3 来自：0254-2（空→04）、0061-3（05→04）、0068-1（05→04）。

## 7. PG 与 vault 校验

### 7.1 PG（`textbook_block_annotations`）

命令（`.venv\Scripts\python.exe`；先 dry-run 后 `--apply`）：

```powershell
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v6.json --model-version textbook-map-v6-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v6_2026-11-07.json           # dry-run
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v6.json --model-version textbook-map-v6-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v6_2026-11-07.json --apply
```

| 校验项 | 结果 |
| --- | --- |
| dry-run 待写/变更 | **839**（全部 model 行，仅 model_version 变化；teacher 958 行 0 变更） |
| apply 写入 | 新建 **0** / 更新 **839** / 未变 **958** |
| active / unique chunk | **1797 / 1797** |
| classification_source | teacher **958** / model **839** |
| status | mapped **1714** / non_content **74** / vocab_gap **9** |
| model 行 model_version | `textbook-map-v6-2026-11-07` × 839 |
| teacher 行版本 | 360=`textbook-review-2026-11-06`、288=`textbook-review-v4-round2-2026-11-06`、310=`textbook-review-v5-round3-2026-11-07`（逐行保留） |
| teacher 行与 v5 写入态备份逐字段差异 | **0** |
| teacher 行 vs reviewed_v6 教师标签（kp/source/status/version/review_status）差异 | **0** |
| model 行（除 model_version 外）与备份差异 | **0** |
| model 行与 reviewed_v6 期望字段差异 | **0** |
| `knowledge_annotations` active | **9092**（gaokao_paper 8007 / mock_exam 1085，未变） |
| RLS / policies / indexes | (True, True) / `pol_textbook_block_annotations_owner` / 3 个索引（与 v5 一致） |
| 幂等（apply 后重复 dry-run） | 待写/变更 **0** |
| `tools/check_all.py --quiet` | **17/17** |
| 写入前备份 | `var/textbook_mapping/backup_pg_draft_before_v6_2026-11-07.json` |

为什么只动 839 个 model 行：9 个变化块**全部是 teacher 行**（教师标签在 PG 里本来就是对的），v6 只改了模型侧预测；PG 里 model 行的 kp/status 与 v5 完全一致，唯一差异是 `model_version`。

### 7.2 Obsidian vault（仅 textbook）

命令（`$env:PYTHONIOENCODING='utf-8'`；先 dry-run 后 `--apply`）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe tools\project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated          # dry-run
.venv\Scripts\python.exe tools\project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated --apply
.venv\Scripts\python.exe var\vault_backup\verify_textbook_links.py --vault "<vault 路径>" --backup-dir "D:\Chilon\var\vault_backup\textbooks_before_links_2026-11-06"
```

| 校验项 | 结果 |
| --- | --- |
| dry-run 计划 | write=**0** / unchanged=**5** |
| apply 写入 | 新写 **0** 个文件 / 幂等不变 **5** / 跳过 0 |
| 块级链接 | **1714**（teacher **875** / model **839**）；vocab_gap 待补 **9**；non_content 74；无标注 0；缺主标注 **0** |
| 链接目标 | 83 个不同 kp_id、1714 次；缺失笔记 **0**、缺别名 **0** |
| 删链接行后与「加链接前基线」比对 | 5 册均 **0 差异**（`textbooks_before_links_2026-11-06`） |
| 无标注表回落模拟 | 链接行 0，输出与原文基线一致 **5/5** |
| mock 投影回归 | 998 文件与 vault 一致 998，差异 **0** |
| 二次 dry-run | write=**0** / unchanged=**5**（0 变更） |
| `verify_textbook_links.py` | **PASS**（格式/每页计数/primary 顺序/secondary/幂等/回落全部通过） |

为什么重投影「写 0 文件」是预期：9 个变化块都是 teacher 行，PG 里教师标签与 round3 写入时一致，且模型侧版本不进渲染；因此 vault 链接面仍为 1714（teacher 875 + model 839）+ 9 待补，重投影确认幂等。

## 8. 方法论局限（必须与数字一起读）

1. **958 是三批非随机样本，不能当全量**：360 是风险分层过采样；288 是 model 池 20% 分层抽样；310 是 pilot100 + 20% 抽样的合并复核（第三批含 273 条完整标签）。三批零重叠，但都不是独立随机样本，exact 比例不能外推为 1797 块的准确率。
2. **规则与评估同源**：这 8 条规则是看着第三批错因写的，834/835 有乐观偏差；`harmed=0` 只保证“没有在这 958 条教师标签上翻车”，不保证新规则在其他未复核块上不误伤。已用逐块命中面核对把风险面限定在目标块（§2 命中面 + §5 守卫），但规则仍依赖字面特征。
3. **窄条件规则天然欠泛化**：本批大量使用连写短语（`二分法…零点`、`在港口停留`、`叫做异面直线`、`内角A，B，C的对边`、`分别根据下列条件解三角形`）来避免抢走同节其它块；OCR 变体/同义表述（如“每次可在港内停靠”或“用二分法求方程的根”）仍可能漏命中。若后续复核发现同类块，应继续用“节号 + 窄条件”扩规则，而不是放宽阈值。
4. **0100-2 是顺带修正，不是第 9 条目标**：它与 0101-1 同模式不可区分（§4）；如评审口径要求严格只算 8 条目标，则指标为 **834/870**，实际运行结果多修 1 块为 **835/870**。本报告两种口径都给出。
5. **剩余 35 条不一致未处理**（全在 288 批），例如 3.4 分段应用、5.7 三角应用复习题、6.4.3 解三角形应用、8.6.2 线面垂直、5.3 导数应用等；这是 v5 已披露的遗留项，v6 按任务边界没有扩面处理。
6. **语义口径问题**：0254-2 教师在 5.7「三角函数的应用」下标注 `kp_04_11_apply`（解三角形应用），词表与节语义不完全一致，但这属于教师标签口径/词表口径问题，不是规则错误；v6 按教师口径执行并在此备注。
7. **未改口径与产物**：未改 v3/v4/v5 工具、未改教师标签、未改 design master/README/review_sheets/抽样工具、未 commit、未跑 alembic。

## 9. 产物与复现

| 产物 | 说明 |
| --- | --- |
| `tools/kb_textbook_map_v6.py` | v6 规则引擎（从 v5 复制；新增 8 条窄 PRI + 2 处顺序调整；`--stage map` / `--stage eval`） |
| `var/textbook_mapping/mapped_1797_v6.json` | 全量 1797 映射（`model_version=textbook-map-v6-2026-11-07`，`rule` 溯源） |
| `var/textbook_mapping/mapped_1797_v6_batch.txt` | 1797 行批次文本 |
| `var/textbook_mapping/mapped_1797_v6_eval.json` | 本报告数字的机器可读来源（metrics / target_check / guard / changes / checks） |
| `var/textbook_mapping/mapped_1797_reviewed_v6.json` | 应用 958 教师标签后的 reviewed（teacher 行与 round3 **逐字段 0 差异**，teacher_version 逐行保留；model 839 行用 v6，标签与 v5 一致） |
| `var/textbook_mapping/backup_pg_draft_before_v6_2026-11-07.json` | PG 写入前备份 |

复现：

```powershell
$env:PYTHONIOENCODING='utf-8'
python tools\kb_textbook_map_v6.py --stage map
python tools\kb_textbook_map_v6.py --stage eval
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var\textbook_mapping\mapped_1797_reviewed_v6.json --model-version textbook-map-v6-2026-11-07 --backup var\textbook_mapping\backup_pg_draft_before_v6_2026-11-07.json
python tools\check_all.py --quiet    # 17/17
```

自检：

| 检查 | 结果 |
| --- | --- |
| mapped 覆盖 / 唯一 block_id | 1797 / 1797 |
| v5→v6 变化块 | 9（8 条目标 + 0100-2 顺带） |
| 8 条目标修复 | 8/8 |
| 新 harmed | 0 |
| 360 / 288 / 310 exact | 327/327、235/270、273/273 |
| 合计 exact | 826→835/870（仅 8 条目标口径 834/870） |
| 反样本守卫 | 12/12 |
| reviewed_v6 teacher 行逐字段差异 | 0（958 行） |
| teacher_version 保留 | 360 / 288 / 310 三版逐行不变 |
| model 行标签变化 | 0（839 行） |
| `python tools/check_all.py --quiet` | 17/17 |

---

> 已写入 PG：`mapped_1797_reviewed_v6.json` → `textbook_block_annotations`（更新 839 个 model 行 / teacher 958 行不变；备份 `var/textbook_mapping/backup_pg_draft_before_v6_2026-11-07.json`）；vault 重投影写 0 文件（幂等）、链接面 1714（teacher 875 / model 839）+ 9 待补。

