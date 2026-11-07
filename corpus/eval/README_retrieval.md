# 检索评测规范与真实教师问题集（v1.1）

> **状态（2026-11-06 更新）：数据库已恢复，首份真人基线已产出。**
> 容器 `chilon-pg-corpus`（宿主 `127.0.0.1:55495`）实测 346 sources / 12902 chunks / 6981 questions；
> 15 条真人问题经 SQL 核验后 `expect_verified` 15/15=true，结果 Recall@8 26.7% / MRR 0.180 / 空结果 13.3%，
> 详见 [`BASELINE_2026-11-06.md`](BASELINE_2026-11-06.md)。本文件继续定义口径与工装；解释边界见基线 §7/§8。
> 阶段 4–5 混合检索原型见 [`HYBRID_BASELINE_2026-11-06.md`](HYBRID_BASELINE_2026-11-06.md)（Qwen3-Embedding + Qdrant + pg_trgm + 可选 Reranker）：同 15 条上无 rerank 组 Recall@8 93.3%（14/15）；复现需 `requirements-ai.txt`，与本节旧检索评测口径分开。
>
> **v2.0 收集模板与 strict 金标（2026-11-07）**：[`teacher_questions.v2.template.json`](teacher_questions.v2.template.json)（60 槽位/30 strict 计划）、[`teacher_questions.v2.schema.json`](teacher_questions.v2.schema.json)、[`V2_COLLECTION_GUIDE.md`](V2_COLLECTION_GUIDE.md)、校验器 `tools/check_teacher_questions_v2.py`。当前 15 条仍为 v1，v2 数据到位后按 D.117 跑正式五组对照。
>
> **首批 v2.0 draft（2026-11-07）**：[`teacher_questions.v2.draft.json`](teacher_questions.v2.draft.json)（60 条来自问题收集1.txt；20 条 strict SQL 候选，`strict_verified=false`）+ [`teacher_questions.v2.draft.gold.json`](teacher_questions.v2.draft.gold.json)（23 个 gold chunk 明细）。待两位人工核验后再冻结，核验表见 `review_sheets/samples/教师问题v2_strict金标核验_2026-11-07.xlsx`。
>
> 历史数字 `Recall@8 55% / MRR 0.451 / 空结果 32% / strict target 0/7` 来自
> `corpus/eval/queries.json`（40 条开发者自拟措辞，D.83 已承认不可信）。
> **它们与新基线不可比，不得引用。** 该文件保留只作对照。

## 1. 测什么，不测什么

| 测 | 不测 |
| --- | --- |
| `knowledge.search` 能否把教师想要的**对象**排进前 k | 生成内容好不好（那是 KB Benchmark v1.0 的 100 分评分） |
| 不同问法的召回：主题词 / 题型+知识点 / 教材概念 / 年份卷别 / 自然语言 | Agent 完整回答、引用准确性 |
| 查找失败的类型：空结果，还是返回了不相关的块 | 教师上传资料（P1）路径 |

度量对象是**检索**，不是回答质量。任何优化先看这里四个数字，再看生成。

## 2. 对象语义：命中的到底是什么（对应 D.78 未决问题）

`knowledge.search` 返回的是**块**（chunk）。一个块可能是题目，也可能是教材正文：

| 对象 | 系统里的表示 | 能否作为命中对象 |
| --- | --- | --- |
| 题（question） | 块 + `question_id` 非空 | 能；用 `object: "question"` 约束 |
| 块（chunk） | 检索返回单元，`excerpt` + 来源定位 | 能；这是默认命中单元 |
| 知识点（knowledge_point） | 块上的 `knowledge_points` 标签（taxonomy） | 目前不独立返回；只能作为块的标签判定 |

**本版口径以“块”为命中单元**，但允许用 `object` 要求“必须是题目块/正文块”。
这样在 D.78 的产品语义未定前也能先量召回；如果将来接口改为直接返回题目或知识点对象，
只需调整 `expect.object` 与判定字段，指标公式不变。

## 3. 什么算命中

一条问题有：

- `expect.any`：1..n 个子句，**OR** 语义。任一子句命中即算“相关命中”（lenient）。
- `expect.strict`：可选，**指定那一个具体对象**必须出现（strict）。

子句结构：

```json
{"field": "text", "contains": "导数", "object": "any"}
{"field": "year", "equals": "2024"}
{"all": [{"field": "year", "equals": "2024"},
         {"field": "paper", "contains": "新课标Ⅰ卷"}]}
```

| 键 | 取值 | 说明 |
| --- | --- | --- |
| `field` | `text` / `excerpt` / `title` / `knowledge_points` / `year` / `paper` / `source_type` | `text` = 块摘要 + 来源标题 |
| `contains` | 字符串 | **逐字**子串匹配（区分大小写，必须与语料原文一致） |
| `equals` | 字符串 | 精确相等；`knowledge_points` 时是标签成员判断 |
| `object` | `any` / `chunk` / `question` / `paragraph` | `question` = 题目块；`paragraph` = 正文块 |
| `all` | 子句数组 | AND 组，用于“年份+卷别”这类复合条件 |

**命中排名**：在 top-k 内，第一个满足 `expect.any` 的块的位置。

**strict target 的定义**（三条同时成立才算）：

1. 块满足 `expect.strict` 子句（例如某道原题的题干片段、某条教材定义原文）；
2. 该块的对象类型满足 `strict.object`（如“这道题必须是题目块，不是教材段落”）；
3. 该块的排名在 top-k 内。

不填 `strict` 的条目**不进入 strict 分母**。strict 是“就是那一条”，lenient 是“相关的回来了”；
两者分开报，是因为“返回了相关题”不代表“找回了老师要的那道题”（D.83 的 strict target 0/7 就是这个问题）。

**判定纪律**：

- 期望片段必须来自语料原文，不能凭记忆写；填完后用 SQL 在 `knowledge_chunks` 里确认存在。
- 一条问题有多个合法目标时，用 `expect.any` 的多个子句表达“集合”；`strict` 只指向一个。
- 期望未核验（`expect_verified=false`）的条目仍可计算，但报告会标记整份为不可信基线。

## 4. 指标口径

设一次运行评了 `N` 条可判定问题（来源被接受、`expect.any` 非空）：

| 指标 | 公式 | 说明 |
| --- | --- | --- |
| Recall@k | 命中条数 / N | top-k 内出现任一 `expect.any` 命中 |
| MRR@k | Σ(1/首个命中排名) / N | 未命中记 0；精确到 4 位小数 |
| 空结果率 | 零命中条数 / N | 检索返回 0 个块 |
| 有结果但不对 | （有块但无 lenient 命中）条数 / N | 与空结果分开，定位“没返回”还是“返回错” |
| 平均命中数 | 总命中块数 / N | 反映 top-k 是否被填满 |
| strict Recall@k | strict 命中条数 / 有 strict 的条数 | 分母不是 N |
| strict MRR@k | Σ(1/strict 排名) / 有 strict 的条数 | 同上 |
| Strict@1 | Top-1 中出现任一 strict gold 的条数 / 有 strict 的条数 | 诊断，不作发布门槛 |
| Strict-all@8 | Top-8 包含全部 strict gold 的条数 / 有 strict 的条数 | 诊断，不作发布门槛 |

**发布门槛（第一阶段，2026-11-07 起）**：只有两项——Recall@8 **≥85%**、Strict Recall@8 **≥70%**；`strict MRR@8` / `Strict@1` / `Strict-all@8` 只作诊断，不设数值门槛、不阻断发布。v2 数据集把 `expect.strict` 升级为 **chunk_id 集合**（金标来自冻结快照），完整口径见 `docs/acceptance_and_retrieval_eval_design_2026-11-07.md` B5。

口径要点：

- Recall 的分母是**问题条数**，不是语料对象数；“检索到相关题”与“找到那道题”分别由 lenient / strict 回答。
- 不计算 precision：教师端第一需求是“能找到”，top-k 里混入相关但不精确的块由后续步骤排序，不在这里惩罚。
- `N` 只包含被接受的来源。默认只算 `origin=teacher`；模拟候选/旧自拟即使跑出来也标记 `trustworthy_baseline=false`。
- 报告同时给分类指标（五类各自 Recall/MRR/空结果/strict），因为混合平均会掩盖“年份卷别全灭”这类单类故障。

## 5. 问题集：五类与规模

目标 **20–40 条，五类各 4–8 条**：

| 类 | 收什么 | 例子（模板提示，不是真数据） |
| --- | --- | --- |
| 主题词 | 一个主题词/章节名/一对易混概念 | “导数”“直线与圆” |
| 题型+知识点 | 题型 + 知识点 | “圆锥曲线的选择题” |
| 教材概念 | 定义/定理/公式/推论/适用条件 | “补集的定义” |
| 年份+卷别 | 年份、卷别、年份段、某年模拟卷 | “2024 新课标Ⅰ卷的题” |
| 自然语言要求 | 难度、易错、数量、用途、来源限制、改编 | “出几道导数压轴题，难度接近高考” |

文件：

| 文件 | 作用 | 能否用于基线 |
| --- | --- | --- |
| `corpus/eval/teacher_questions.json` | **真实教师问题集（待收集）** | 能（且需 `expect_verified=true`） |
| `corpus/eval/teacher_questions.template.json` | 30 个空槽位的收集模板（五类各 6） | 不能，空白模板 |
| `corpus/eval/teacher_questions.candidates.json` | 25 条**模拟候选**（Agent 拟定，显式标注） | 不能，仅演练工装/给教师看样例 |
| `corpus/eval/teacher_questions.schema.json` | 结构定义（JSON Schema Draft 2020-12，已用 jsonschema 校验模板与候选） | — |
| `corpus/eval/queries.json` | 旧 40 条开发者自拟 | 不能，只作对照 |
| `corpus/eval/teacher_questions.v2.template.json` | **v2.0 收集模板：60 槽位，30 strict 计划** | 不能，空白模板 |
| `corpus/eval/teacher_questions.v2.schema.json` | v2 结构：strict 为 chunk_id 金标集合 | — |
| `corpus/eval/V2_COLLECTION_GUIDE.md` | v2 收集/核验/冻结指南 | — |

## 6. 收集工装与真人输入清单

模板内 `instructions` / `collection_protocol` 是操作说明，核心纪律：

1. 由**真实高中数学教师**在不知道检索实现的前提下，说出他真正会提的检索需求；**逐字记录**，不改写成“系统友好”的关键词。
2. 一条只表达一个检索意图；一句话多个要求就拆条。
3. 采样必须自然：**不能只收集系统答得对的问题**，否则基线虚高。
4. 期望由**另一位核验人**（不是提问教师）在语料中 SQL 确认后填写，`expect_verified` 才能置 `true`。
5. 模拟候选永远保持 `origin=simulated_candidate`，不得改写成 `teacher`。

**需要真人提供的输入（缺一不可）：**

| # | 输入 | 谁提供 | 写成什么 |
| --- | --- | --- | --- |
| 1 | 20–40 条教师原话检索需求（五类各 4–8） | 真实数学教师（建议 2–3 位，不同教龄/年级） | `queries[].text`（逐字） |
| 2 | 教师背景 | 收集人 | `contributor`（如“高三/教龄 3 年/未用过系统”） |
| 3 | 收集日期 | 收集人 | `collected_at`（YYYY-MM-DD） |
| 4 | 每条期望命中的对象（至少一条 `expect.any`；要“就是那一道”时再加 `expect.strict`） | 语料核验人（SQL 确认后） | `expect` |
| 5 | 期望已核验的确认 | 语料核验人 | `expect_verified: true` |
| 6 | 教师/核验人复核签字（措辞仍是原话、目标真实存在） | 两位参与者 | `provenance.note` + 版本记录 |

填写完成后另存为 `corpus/eval/teacher_questions.json`，把 `provenance.status` 改为
`real_teacher`、`real_teacher_confirmed: true`，再跑第 7 节的一键命令。

## 7. 运行方式

### 7.1 不需要数据库（今天就能跑）

```powershell
# 指标逻辑自测：假数据，验证 Recall/MRR/空结果/strict/报告渲染
python tools\eval_retrieval.py --selftest

# 问题集结构校验（不连数据库）
python tools\eval_retrieval.py --check-input --input corpus\eval\teacher_questions.json
```

自测通过时退出码 0，并在 `var\retrieval\selftest.json` / `selftest.md` 写一份
**明确标注“非基线”**的样例报告（用于验证 JSON+MD 输出链路）。

### 7.2 真实评测（数据库恢复 + 问题集到位后的一键命令）

```powershell
# 1) 指向真实知识库（测试用 admin 账号；见 7.3 为什么不是应用角色）
$env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:chilon_test_only@localhost:5432/chilon"

# 2) 用 .venv 解释器跑（真实检索要后端依赖 sqlalchemy / httpx / psycopg）
.\.venv\Scripts\python.exe tools\eval_retrieval.py `
    --input corpus\eval\teacher_questions.json `
    --k 8 `
    --out-prefix var\retrieval\baseline_2026-11-06

echo $LASTEXITCODE    # 0 = 完成
```

输出：

- `var\retrieval\baseline_2026-11-06.json`：完整报告（run 元信息、口径、指标、分类指标、逐条排名、排除项、trust 判定）。
- `var\retrieval\baseline_2026-11-06.md`：同一份报告的人读版本，首屏就是“可信基线：是/否 + 原因”。
- 终端摘要：`Recall@k / MRR / 空结果 / 有结果但不对 / strict`。

旧 40 条仅作对照（结果一定标记不可信，不要写进汇报当基线）：

```powershell
.\.venv\Scripts\python.exe tools\eval_retrieval.py `
    --input corpus\eval\queries.json --include-untrusted `
    --out-prefix var\retrieval\legacy_queries_compare
```

### 7.3 环境变量与前置条件

| 变量 | 必需 | 含义 |
| --- | --- | --- |
| `CHILON_TEST_DATABASE_URL` | 是 | 可读平台语料的 PostgreSQL 连接串，必须带异步驱动 `+psycopg` |
| `CHILON_DATABASE_URL` / 其他 | 否 | 本脚本不读取；评测只用上面的测试变量，避免误连生产库 |

前置条件：

1. PostgreSQL 已启动并**已导入平台语料**（D.83 的快照是 346 套 / 6981 题）。
   先查 `knowledge_sources` / `knowledge_questions` / `knowledge_chunks` 的条数，确认当前库不是空库。
2. URL 使用 `postgresql+psycopg://...`（项目驱动是 psycopg3，不是 asyncpg）。
3. 账号需能读 `knowledge_chunks` / `knowledge_sources` / `knowledge_questions`。
   评测走 `db.system_session()`（平台语料是 platform scope，与教师实际可见内容一致）；
   **用受 RLS 限制的应用角色连会看到 0 条命中，那是权限问题，不是检索质量**。README 记录这一限制。
4. 真实评测用 `.venv\Scripts\python.exe`；当前仓库环境里 PATH 的裸 `python` 没有后端依赖（脚本会以退出码 4 明确提示）。

阶段 4–5 的混合检索原型是另一条评测链路：见 `HYBRID_BASELINE_2026-11-06.md` §11（Qdrant + `tools/eval_hybrid.py`，额外依赖见 `requirements-ai.txt`），不要用本节的旧 `knowledge_search` 命令替代。

### 7.4 退出码

| 码 | 含义 | 脚本行为 |
| ---: | --- | --- |
| 0 | 完成 / 自测通过 / 校验通过 | 写报告并打印摘要 |
| 1 | 自测失败 | 指标逻辑回归，先修脚本 |
| 2 | 无法评测：`CHILON_TEST_DATABASE_URL` 未设置 | 打印原因与下一步，不编数字 |
| 3 | 无法评测：问题集缺失 / 不合法 / 无可判定样本 | 同上 |
| 4 | 无法评测：缺少 Python 依赖 | 提示改用 `.venv` 解释器 |
| 5 | 无法评测：数据库不可达或查询失败 | 提示检查服务、URL、账号权限；预检失败可加 `--no-preflight` |

无数据库时**不会打印堆栈，也不会用假数据凑基线**。

### 7.5 与旧 CLI 的差异（刻意改变）

旧脚本没有参数，固定读 `corpus/eval/queries.json`。新脚本：

- 默认输入改为 `corpus/eval/teacher_questions.json`（真实教师问题集），缺失时以退出码 3 说明下一步；
- 旧的 40 条不再隐式进入评测，复现对照必须显式加
  `--input corpus/eval/queries.json --include-untrusted`，报告会标记不可信；
- 新增 `--k / --limit / --out-prefix / --out-json / --out-md / --check-input / --selftest / --no-preflight`；
- stdout 摘要仍是 Recall / MRR / 空结果 / strict 四项，另加“有结果但不对”和输出文件路径。

这么改是为了防止“跑一下旧集又得到一个 55%”继续被当成基线。

## 8. 已知限制与未决

- **对象语义（D.78）仍未由产品拍板**：当前以块为命中单元，用 `object` 约束区分题目/正文；知识点只能作为标签判定。
- **语料快照不可复现到字节级**：报告记录 git commit、问题集 sha256、k，但没有数据库快照版本；跨天对比时要自己记录语料是否变化。
- **多目标问题**：一条问题若有多个可接受目标，用 `expect.any` 列举；strict 只能指一个对象。
- **不覆盖 P1 教师上传**：平台语料是 P0；教师私有内容不在此评测范围。
- **模拟候选的期望未核验**：`candidates.json` 只能演练工装，不能产出基线；当前唯一可信基线见 [`BASELINE_2026-11-06.md`](BASELINE_2026-11-06.md)，本文件不重复维护数字。
- 可选后续（不在本次写入范围）：把 `--selftest` 加进 `tools/check_all.py` 的检查清单。

## 9. 版本记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-11-06 | 初版：对象/命中/strict/指标口径；问题集 schema、30 条模板、25 条模拟候选；`tools/eval_retrieval.py` 改造（外部问题集、JSON+MD、DB 缺失干净失败、17 项自测）。数据库不可用，未产生基线数字。 |
| v1.1 | 2026-11-06 | DB 恢复后产出首份真人基线（15 条真人问题、`expect_verified` 15/15，Recall@8 26.7% / MRR 0.180 / 空结果 13.3%，见 `BASELINE_2026-11-06.md`）；顶部状态与第 8 节相应更新，口径与工装说明不变。 |
| v1.2 | 2026-11-07 | 指标扩展：新增 Strict@1、Strict-all@8 两个诊断指标（均只在 strict 子集计算）；明确第一阶段发布门槛只有 Recall@8 ≥85% 与 Strict Recall@8 ≥70%，MRR@8/Strict@1/Strict-all@8 不阻断发布；v2 数据集把 strict 升级为 chunk_id 集合（见设计稿 B5/D.117）。 |
| v1.3 | 2026-11-07 | v2.0 收集模板与 strict 金标 schema 落地：60 槽位（五类各 12）、30 条 strict（定义 8/定理 6/公式 6/题目 10）、chunk_id 金标、双人核验与 κ 要求；新增 `V2_COLLECTION_GUIDE.md` 与 `tools/check_teacher_questions_v2.py`。 |
| v1.4 | 2026-11-07 | 首批 v2.0 draft：60 条问题来自问题收集1.txt，20 条 strict SQL 候选（定义 9/定理 6/公式 5），`strict_verified=false`；新增 draft gold 明细、核验表导出与 `--allow-unverified` draft 校验；待两位人工核验后冻结。 |
