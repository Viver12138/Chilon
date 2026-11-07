---
type: report
title: 教材映射 v5：两条窄排除修正 + 全量重跑与 PG/vault 更新
updated: 2026-11-07
status: v5-applied
model_version: textbook-map-v5-2026-11-07
---

# 教材映射 v5：两条窄排除修正 + 全量重跑与 PG/vault 更新

> 输入：`mapped_1797_v4.json`（v4 基线）、`blocks_1797_with_structure.json`、`structure_5books.json`、`corpus/eval/kp_vocab.md`。
> 映射阶段（`--stage map`）**不读取教师标签**；教师标签只在评估阶段（`--stage eval`）读取，来源为
> `review_360_parsed.json`（第一批 360）与 `review_round2_parsed.json`（第二批 288），合计 **648 条**。
> 未改 `kb_textbook_map_v3.py` / `kb_textbook_map_v4.py`；未调 OCR。PG 与 vault 写入见 §6。

## 0. 结论先行

- **5 条 v3→v4 改坏块 5/5 全部修好**；在 648 教师标签上**新 harmed = 0**。
- **360 子集 exact 保持 327/327**（不回退）；**288 子集 exact 229 → 234 /270**（84.8% → 86.7%，期望值达成）；648 合计 exact **556 → 561 /597**（93.1% → 94.0%），模块命中 **589/597 不变**。
- 修法只有两条规则各加一个**窄排除词**，排除后**回落 v3 基线**（不硬编码目标标签）；全量 1797 中 v4→v5 只有 **5 块**变化，**1149 个 model 行变化 0**。
- PG：active **1797**（teacher **648** / model **1149**），model 行 `model_version=textbook-map-v5-2026-11-07`，teacher 行版本按批次保留（360=`textbook-review-2026-11-06` / 288=`textbook-review-v4-round2-2026-11-06`），`knowledge_annotations` **9092 未变**，重复 dry-run **0 变更**，`check_all` **17/17**。
- vault：教材块级链接 **1740**（teacher **602** / model **1138**）+ 1 条待补（vocab_gap），目标 missing **0**；本次重投影**写 0 文件**（5 册与重投影前逐字节一致），二次 dry-run **0 变更**。

## 1. 修法：只加两条窄排除条件

v5 = v4 规则引擎（CAT/SUM/PRI/SEC/FILL 结构、阈值、`SECTION_KP`、`SEC_SKIP` 全部不动）+ 两条 PRI 规则的 `neg`。
排除命中时不另设目标标签，而是**让该块回落到 v3 基线**（v3 在 5 条上本来就等于教师标签），因此改动面可审计、无新增口径。

| 规则 | v4 条件 | v5 增加的排除词（neg） | 效果 |
| --- | --- | --- | --- |
| 必修一 · 3.2 最值/值域 → `kp_02_03_range` | `最大值\|最小值\|值域` | `函数的基本性质\|定义证明\|证明[^。]{0,12}单调` | 排除 3.2 节导语（正文含节标题“函数的基本性质”）与“例3 根据定义证明…单调递增”这类定义证明题 |
| 必修一 · 4.5.3 指数增长模型 → `kp_02_08_exponential` | `浮萍\|增长率为\|a^t\|y=a` | `函数模型\|碳14\|马尔萨斯\|人口模型\|建模` | 排除“函数模型的应用”语境（马尔萨斯人口模型、碳14 半衰期、数学建模活动） |

### 1.1 为什么 3.2 不能用裸“单调”做排除

任务给的候选排除是 `函数的基本性质|单调|定义证明`。实测**裸“单调”会误伤同节正确样本**：
`TB-B1-0088-1-p0088-01` 教师标签 = `kp_02_03_range`，其正文含“函数 f(x)=2/(x−1) 在区间 [2，6] 上**单调递减**”，
若用裸“单调”它会被排除并回落 v3 的 `kp_02_04_monotonic` → **新 harmed**。因此 v5 把“单调”收窄为
“证明…单调 / 定义证明”这类**证明题型特征**，并把导语特征（节标题“函数的基本性质”）单独列出。

### 1.2 排除词实际命中面（必修第一册 3.2 / 4.5.3 全部块）

**3.2 节（必修一，9 块）**：只有 0083、0086 同时命中主条件与排除词 → 回落 v3；其余 7 块（含教师=range 的 0087-2、0088-1）不受影响。

| block_id | 主条件 | 排除词命中 | v5 结果 |
| --- | --- | --- | --- |
| `TB-B1-0083-1-p0083-01` | 是 | `函数的基本性质` | `kp_02_04_monotonic`（v3 基线） |
| `TB-B1-0084-1-p0084-01` | 否 | — | `kp_02_04_monotonic`（未受影响） |
| `TB-B1-0085-1-p0085-01` | 否 | — | `kp_02_04_monotonic`（未受影响） |
| `TB-B1-0085-2-p0085-02` | 否 | — | `kp_02_04_monotonic`（未受影响） |
| `TB-B1-0086-1-p0086-01` | 是 | `定义证明` | `kp_02_04_monotonic`（v3 基线） |
| `TB-B1-0087-1-p0087-01` | 是 | 否 | `kp_02_03_range`（PRI 保持） |
| `TB-B1-0087-2-p0087-02` | 是 | 否 | `kp_02_03_range`（PRI 保持，教师=range） |
| `TB-B1-0088-1-p0088-01` | 是 | 否 | `kp_02_03_range`（PRI 保持，教师=range） |
| `TB-B1-0088-2-p0088-02` | 是 | 否 | `kp_02_03_range`（PRI 保持） |

**4.5.3 节（必修一，38 块）**：只有 0155、0157-2、0157-3 同时命中主条件与排除词；其余 35 块本来就是 v3 基线（排除词对它们生效也不产生任何改动）。反向样本 0162-2（浮萍 y=a^t，教师=exponential）与 0168-1（教师=exponential）都不含排除词，保持 v4/v3 结果。

| block_id | 主条件 | 排除词命中 | v5 结果 |
| --- | --- | --- | --- |
| `TB-B1-0155-1-p0155-01` | 是 | `函数模型` | `kp_02_12_abstract`（v3 基线） |
| `TB-B1-0157-2-p0157-02` | 是 | `碳14` | `kp_02_12_abstract`（v3 基线） |
| `TB-B1-0157-3-p0157-03` | 是 | `马尔萨斯` | `kp_02_12_abstract`（v3 基线） |
| `TB-B1-0162-2-p0162-02` | 是 | 否 | `kp_02_08_exponential`（PRI 保持，教师=exponential） |
| `TB-B1-0168-1-p0168-01` | 否 | 否 | `kp_02_08_exponential`（v3 基线，教师=exponential） |

## 2. 5 条改坏块：before / after

| # | block_id | 节 | 教师标签 | v3 | v4（错） | v5 | v4 规则 | v5 排除依据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `TB-B1-0083-1-p0083-01` | 3.2 函数的基本性质（节导语） | `kp_02_04_monotonic` | `kp_02_04_monotonic` | `kp_02_03_range` | **`kp_02_04_monotonic`** ✅ | `PRI:3.2 节内最值/值域` | `函数的基本性质` |
| 2 | `TB-B1-0086-1-p0086-01` | 3.2 例3 定义证明单调 | `kp_02_04_monotonic` | `kp_02_04_monotonic` | `kp_02_03_range` | **`kp_02_04_monotonic`** ✅ | `PRI:3.2 节内最值/值域` | `定义证明` |
| 3 | `TB-B1-0155-1-p0155-01` | 4.5.3 函数模型的应用（导语） | `kp_02_12_abstract` | `kp_02_12_abstract` | `kp_02_08_exponential` | **`kp_02_12_abstract`** ✅ | `PRI:4.5.3 节内指数增长模型` | `函数模型` |
| 4 | `TB-B1-0157-2-p0157-02` | 4.5.3 碳14 半衰期 | `kp_02_12_abstract` | `kp_02_12_abstract` | `kp_02_08_exponential` | **`kp_02_12_abstract`** ✅ | `PRI:4.5.3 节内指数增长模型` | `碳14` |
| 5 | `TB-B1-0157-3-p0157-03` | 4.5.3 马尔萨斯人口模型 | `kp_02_12_abstract` | `kp_02_12_abstract` | `kp_02_08_exponential` | **`kp_02_12_abstract`** ✅ | `PRI:4.5.3 节内指数增长模型` | `马尔萨斯` |

同节正确样本守卫（v4 与 v5 一致，且等于教师标签）：

| block_id | 节 | 教师标签 | v4 | v5 | 保持 |
| --- | --- | --- | --- | --- | --- |
| `TB-B1-0087-2-p0087-02` | 3.2 | `kp_02_03_range` | `kp_02_03_range` | `kp_02_03_range` | ✅ |
| `TB-B1-0088-1-p0088-01` | 3.2 | `kp_02_03_range` | `kp_02_03_range` | `kp_02_03_range` | ✅ |
| `TB-B1-0162-2-p0162-02` | 4.5.3 | `kp_02_08_exponential` | `kp_02_08_exponential` | `kp_02_08_exponential` | ✅ |
| `TB-B1-0168-1-p0168-01` | 4.5.3 | `kp_02_08_exponential` | `kp_02_08_exponential` | `kp_02_08_exponential` | ✅ |
| `TB-B1-0165-1-p0165-01` | 4.5.3（章末小结） | `kp_02_11_zero` | `kp_02_11_zero` | `kp_02_11_zero` | ✅ |
| `TB-B1-0168-2-p0168-02` | 4.5.3 | `kp_02_09_logarithm` | `kp_02_09_logarithm` | `kp_02_09_logarithm` | ✅ |

## 3. 648 教师标签上的指标（分母 597）

分母口径：教师有标签且模型非 `non_content`。第一批 360（教师内容 331）→ 分母 **327**；第二批 288（教师内容 271）→ 分母 **270**；合计 **648 条标签 / 597 分母**。

| 子集 | 分母 | 版本 | module | exact | any |
| --- | ---: | --- | ---: | ---: | ---: |
| 360（第一批） | 327 | v3 | 308 | 253 | 253 |
| 360 | 327 | v4 | 327 | 327 | 327 |
| 360 | 327 | **v5** | **327** | **327** | **327** |
| 288（第二批） | 270 | v3 | 258 | 200 | 200 |
| 288 | 270 | v4 | 262 | 229 | 229 |
| 288 | 270 | **v5** | 262 | **234** | **234** |
| 648 合计 | 597 | v3 | 566 | 453 | 453 |
| 648 合计 | 597 | v4 | 589 | 556 | 556 |
| 648 合计 | 597 | **v5** | **589** | **561** | **561** |

- v4→v5 在 648 上是 **fixed 5 / harmed 0 / still 36**，仍错的 36 条全部在 288 子集（270−234），v5 未改动它们（不在本次修正范围；v4 已披露的遗留项）。
- 288 子集模块命中 262/270 未变：5 条修复块的模块（02）本就判对，错的是节内 kp，故 exact 提升而模块不变。

## 4. 全量变化审计（v4→v5：1797 中仅 5 块）

| # | block_id | 节 | before → after | v5 规则 | 教师标签 | 审计判断 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `TB-B1-0083-1-p0083-01` | 3.2 | `kp_02_03_range` → `kp_02_04_monotonic` | v3_base（排除后回落） | `kp_02_04_monotonic` | 修好：节导语同时谈单调/最值，教师判单调 |
| 2 | `TB-B1-0086-1-p0086-01` | 3.2 | `kp_02_03_range` → `kp_02_04_monotonic` | v3_base | `kp_02_04_monotonic` | 修好：定义证明单调 |
| 3 | `TB-B1-0155-1-p0155-01` | 4.5.3 | `kp_02_08_exponential` → `kp_02_12_abstract` | v3_base | `kp_02_12_abstract` | 修好：函数模型应用导语 |
| 4 | `TB-B1-0157-2-p0157-02` | 4.5.3 | `kp_02_08_exponential` → `kp_02_12_abstract` | v3_base | `kp_02_12_abstract` | 修好：碳14 半衰期建模 |
| 5 | `TB-B1-0157-3-p0157-03` | 4.5.3 | `kp_02_08_exponential` → `kp_02_12_abstract` | v3_base | `kp_02_12_abstract` | 修好：马尔萨斯人口模型 |

- 变化块全部是 **teacher 行**：1149 个 model 行的 kp/status/secondary 变化 = **0**（v5 没有触及任何 model 块）。
- 其余 v4 结构完全复现：`rule` 命中 v3_base 1228 / PRI 283 / SEC 263 / FILL 16 / CAT 5 / SUM 2；基线未命中块与 v3 逐块一致（差异 0）。
- 状态：v5 模型标签（未叠加教师）mapped 1746 / non_content 43 / vocab_gap 8，与 v4 完全一致（无状态迁移）。

## 5. 状态分布（最终 reviewed_v5 口径）

| 状态 | 全量 1797（模型标签） | reviewed_v5 | teacher 648 | model 1149 |
| --- | ---: | ---: | ---: | ---: |
| mapped | 1746 | 1740 | 602 | 1138 |
| non_content | 43 | 56 | 46 | 10 |
| vocab_gap | 8 | 1 | 0 | 1 |

- teacher 行版本：`textbook-review-2026-11-06` 360 行 + `textbook-review-v4-round2-2026-11-06` 288 行，**逐行保留**。
- reviewed_v5：1797 行（teacher 648 / model 1149），teacher 648 行与 `mapped_1797_reviewed_round2.json` **逐字段 0 差异**。

## 6. PG 与 vault 校验

### 6.1 PG（`textbook_block_annotations`）

写入命令（venv python；先 dry-run 后 `--apply`）：

```powershell
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v5.json --model-version textbook-map-v5-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v5_2026-11-07.json           # dry-run
.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --reviewed var/textbook_mapping/mapped_1797_reviewed_v5.json --model-version textbook-map-v5-2026-11-07 --backup var/textbook_mapping/backup_pg_draft_before_v5_2026-11-07.json --apply
```

| 校验项 | 结果 |
| --- | --- |
| active / unique chunk | 1797 / 1797 |
| classification_source | teacher 648 / model 1149 |
| status | mapped 1740 / non_content 56 / vocab_gap 1 |
| model 行 model_version | `textbook-map-v5-2026-11-07` × 1149 |
| teacher 行版本 | `textbook-review-2026-11-06` × 360、`textbook-review-v4-round2-2026-11-06` × 288（逐行不变） |
| teacher 行与 v4 写入态备份逐字段差异 | **0** |
| model 行（除 model_version 外）与备份差异 | **0** |
| model / teacher 行与 reviewed_v5 期望字段差异 | **0 / 0** |
| `knowledge_annotations` active | **9092**（gaokao_paper 8007 / mock_exam 1085，未变） |
| RLS / policies / indexes | (True, True) / `pol_textbook_block_annotations_owner` / 3 个索引（与 v4 一致） |
| 幂等（apply 后重复 dry-run） | 待写/变更 **0** |
| `tools/check_all.py` | **17/17** |
| 写入前备份 | `var/textbook_mapping/backup_pg_draft_before_v5_2026-11-07.json` |

### 6.2 Obsidian vault（`<vault 路径>`，仅 textbook）

命令（先备份 5 册到 `var/vault_backup/textbooks_before_v5_2026-11-07/`）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe tools/project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated          # dry-run
.venv\Scripts\python.exe tools/project_restricted_corpus.py --vault "<vault 路径>" --only textbook --force-generated --apply
```

| 校验项 | 结果 |
| --- | --- |
| 教材笔记 / 块 | 5 / 1797 |
| 块级链接 | **1740**（teacher **602** / model **1138**）；vocab_gap 待补 **1**；non_content 56；missing 0 |
| 链接目标 | 83 个不同 kp_id，缺失笔记 **0**，缺别名 0 |
| `删链接行` 后与「加链接前基线」比对 | 5 册均 **0 差异**（`textbooks_before_links_2026-11-06`） |
| 本次 apply 写文件 | 新写 **0** / 幂等不变 **5** / 跳过 0（5 册与重投影前备份**逐字节一致**） |
| 当前 5 册 vs v5 前备份 | 字节相同 5/5、去链接行相同 5/5 |
| 二次 dry-run | write=0 / unchanged=5（**0 变更**） |
| mock 投影回归 | 998 文件与 vault 一致 998、差异 0（mock 未受影响） |
| 高考卡聚合 | 6324 张，sha256 `87f6a569…` 前后一致 |
| `verify_textbook_links.py` | **PASS**（格式/每页计数/primary 顺序/secondary/幂等/回落全部通过） |

为什么本次重投影“写 0 文件”是预期行为：5 条修正块在 PG 里是 **teacher 行**，其 `kp_primary` 来自教师标签、在 round2 写入时就已经是正确的；v5 只改了模型侧的 `model_version` 与这 5 块的**模型预测**，而模型预测不进入 vault 渲染。因此 vault 链接面（1740 teacher 602/model 1138 + 1 待补）与 round2 投影一致，重投影确认幂等。

## 7. 方法论局限（必须与数字一起读）

1. **648 是两批非随机样本，不能当全量**：360 是风险分层过采样（低置信/vocab_gap/non_content 被放大）；288 是 model 池 20% 分层抽样（全量 vocab_gap/non_content + 按册比例 + 置信分层）。两批零重叠，但都不是独立随机样本，其 exact 比例不能外推为 1797 块的准确率。
2. **规则与评估同源**：两条排除词是看着这 5 条错因写的，288 上的 229→234 有乐观偏差；`harmed=0` 只保证“没有在这批教师标签上翻车”，不保证新排除词在其他未复核块上不误伤（已用同节 9+38 块逐块核对命中面，风险面已限定在这两节）。
3. **剩余 36 条不一致未处理**：全部在 288 子集（270−234），例如 3.4 分段函数、5.7 复习题、2.1 基本不等式等；本次任务只修 5 条改坏块，未扩规则，避免引入新的未验证改动。
4. **字面特征词的边界**：排除词依赖“函数的基本性质 / 定义证明 / 函数模型 / 碳14 / 马尔萨斯 / 人口模型 / 建模”等字面表述，OCR 变体或同义表述（如“人口增长模型”以外的说法）仍可能漏排；下次复核若发现同类块，应继续用“节号 + 窄排除”而非放宽阈值。
5. **360 的 327/327 仍是拟合样本结果**：v5 对 360 无任何改动，该数字不能解读为全量 100%。
6. **未改口径与产物**：未改 v3/v4 工具、未改教师标签、未改 design master / README / review_sheets / 抽样工具、未 commit。

## 8. 产物与复现

| 产物 | 说明 |
| --- | --- |
| `tools/kb_textbook_map_v5.py` | v5 规则引擎（从 v4 复制；仅两条 PRI 规则加 `neg`，`--stage map` / `--stage eval`） |
| `var/textbook_mapping/mapped_1797_v5.json` | 全量 1797 映射（`model_version=textbook-map-v5-2026-11-07`，`rule` 溯源） |
| `var/textbook_mapping/mapped_1797_v5_batch.txt` | 1797 行批次文本 |
| `var/textbook_mapping/mapped_1797_v5_eval.json` | 本报告数字的机器可读来源（metrics / fixed / harmed / guard / changes / checks） |
| `var/textbook_mapping/mapped_1797_reviewed_v5.json` | 应用 648 教师标签后的 reviewed（teacher 行与 round2 **逐字段 0 差异**，model 行用 v5） |
| `var/textbook_mapping/backup_pg_draft_before_v5_2026-11-07.json` | PG 写入前备份 |
| `var/vault_backup/textbooks_before_v5_2026-11-07/` | vault 5 册写入前备份 |

复现：

```powershell
python tools/kb_textbook_map_v5.py --stage map
python tools/kb_textbook_map_v5.py --stage eval
.venv\Scripts\python.exe var\vault_backup\verify_textbook_links.py --vault "<vault 路径>" --backup-dir "D:\Chilon\var\vault_backup\textbooks_before_links_2026-11-06"
python tools/check_all.py --quiet    # 17/17
```

自检：

| 检查 | 结果 |
| --- | --- |
| mapped 覆盖 / 唯一 block_id | 1797 / 1797 |
| v4→v5 变化块 | 5（全部落在 5 条改坏块上） |
| 5 条改坏块修复 | 5/5 |
| 新 harmed | 0 |
| 360 子集 exact 不回退 | 327/327 |
| 288 子集 exact | 234/270（v4 229） |
| reviewed_v5 teacher 行逐字段差异 | 0（648 行） |
| teacher_version 保留 | 360 / 288 两版逐行不变 |
| `python tools/check_all.py --quiet` | 17/17 |

---

> 已写入 PG：`mapped_1797_reviewed_v5.json` → `textbook_block_annotations`（更新 1149 个 model 行 / teacher 648 行不变；备份 `var/textbook_mapping/backup_pg_draft_before_v5_2026-11-07.json`）；vault 重投影写 0 文件（幂等）、链接面 1740（teacher 602 / model 1138）+1 待补。

