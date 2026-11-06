# Obsidian ↔ PostgreSQL 同步契约（草案 v0.2）

> 状态：**草案 / 待评审**（2026-11-06）
> 适用范围：Chilon 高中数学知识库（vault `C:\Users\Viver\Desktop\高中数学`）+ PostgreSQL `chilon`（容器 `chilon-pg-corpus`）+ Qdrant 派生索引
> 本文件回答三件事：**谁是唯一事实源（SSOT）、哪些字段谁可改、改动怎么同步与冲突怎么裁决**。
> 配套落地：第一版标注导入工具 `tools/kb_annotations_to_pg.py`，导入报告 `var/annotations/import_report.md`。

---

## 0. 一页结论（TL;DR）

| 问题 | 结论 |
| --- | --- |
| 谁是 SSOT？ | **PostgreSQL 是唯一事实源**。Obsidian 是阅读/审校/组织工作区，Qdrant 是派生索引 |
| 谁可以直接改数据？ | Obsidian 可改**内容与人工审校字段**（知识点/方法/答案解析修订/审校状态/人工备注）；**结构字段只读** |
| 改动怎么进 PG？ | 审校完成后由同步程序读取 Obsidian（或标注 JSON），带 `human_edited`、内容哈希、版本、审校人/时间写入 PG |
| PG 怎么影响 Obsidian？ | 只做**派生投影**：题卡 `knowledge_points`、索引页、统计页由 PG 生成；投影文件不回写 PG |
| 冲突怎么办？ | 以「内容哈希 + version + last-reviewed」三方判定；**人工审校优先**；PG 结构字段不接受 Obsidian 改 |
| `current_knowledge_points` 是什么？ | **旧工作台遗留的中文模块名缓存，不是新事实源**。kp_id 的 SSOT 是 `knowledge_annotations`；迁移评审前该列保持旧语义，hybrid retrieval 必须读 `knowledge_annotations`（不得依赖该列新旧格式） |
| Qdrant 地位？ | **派生索引，可从 PG 全量重建**，任何情况下不作为事实源 |
| 当前进度 | 6050 条标注已从 Obsidian JSON 导入 PG（8007 条 active 标注，primary 6045）；`current_knowledge_points` 已还原为旧缓存（4748/6050 非空）；旧基线 Recall@8 26.7%（4/15）复现通过；双向同步程序尚未实现 |

---

## 1. 术语与边界

| 术语 | 含义 |
| --- | --- |
| SSOT | Single Source of Truth，唯一事实源；本契约指 PostgreSQL `knowledge_*` 表 |
| vault | Obsidian 库（Markdown + YAML + `02_Processed/Annotations/*.json`），只读账本之外的编辑区 |
| qid | vault 题目稳定 ID，如 `gk_2016_sichuan_arts_q05`（`gk_{年}_{卷别}_{科类}_q{题号}`） |
| kp_id | level-3 知识点 ID，如 `kp_09_08_eccentricity`（词表 `10_Indexes/知识点词表.md`，120 条 / 17 模块） |
| 投影 | 由 PG 生成、写回 Obsidian 的派生内容（题卡知识点、索引、统计），不承载新事实 |
| 内容哈希 | 参与同步的字段规范化后的 SHA-256；用于判定“是否真的改了” |

### 1.1 PG SSOT 的表与字段边界

| 表 | 在 SSOT 中的角色 | 关键字段（边界） |
| --- | --- | --- |
| `knowledge_sources` | 卷/教材来源身份 | `source_type`(gaokao_paper/mock_exam/textbook)、`year`、`title`、`metadata`；**权威** |
| `knowledge_document_versions` | 每次导入的版本与原始文件校验 | `version_no`、`storage_key`、`checksum_sha256`、`lifecycle_status`；**权威** |
| `knowledge_questions` | 题目结构 | `id`(UUID)、`document_version_id`、`question_no`、`stem_locator`、`answer_locator`、`current_paper_question_type`；结构字段**权威**。`current_knowledge_points`(TEXT[]) 是**旧工作台遗留缓存（非 SSOT）**，见 §6.2 |
| `knowledge_chunks` | 可检索文本块 | `chunk_key`、`ordinal`、`text_content`、`text_hash`、`locator`、`content_kind`；**权威** |
| `knowledge_annotations` | 派生标注（带版本） | `annotation_type`、`value`、`classification_source`(rule/model/teacher)、`confidence`、`model_version`、`superseded_by`、`created_by`、`created_at`；**权威** |
| `knowledge_reviews` | 人工审校记录 | `review_type`、`target_id`、`decision`、`target_hash`、`reviewer_id`、`notes`、`reviewed_at`；**权威** |
| `knowledge_categories` | 分类树（gaokao/textbooks/mock） | `scope`、`key`、`name`；**权威** |
| `knowledge_indexing_jobs` | 索引任务（Qdrant/全文） | 状态与指标；**运行态，非内容事实** |

**边界原则**：

1. 题面、答案、解析、来源、切分位置、知识点标注的“真值”只在 PG（及其导入前的标准化源文件）中认定，Obsidian 内容视为**待审校输入**。
2. `current_*` 字段（`current_knowledge_points` / `current_paper_question_type`）是**投影/缓存**，不允许人工直接写 PG。其中 `current_knowledge_points` 当前是**旧工作台遗留的中文模块名缓存**（见 §6.2），不是 kp_id 的事实源；新事实一律落 `knowledge_annotations`。
3. 词表（`kp_id` 定义）本次仍以 vault `10_Indexes/知识点词表.md` 为草案来源；正式化后应进 PG `knowledge_categories`/独立 `knowledge_points` 表（**open item**）。

### 1.2 当前已知的映射缺口（重要）

PG `knowledge_questions` **没有 qid 列**，而 Obsidian 与标注 JSON 都以 qid 为主键。当前导入工具的映射是派生规则：

```
qid → document_id + question_number
    → OCR_JSON source_tex 相对路径 + 题号
    → knowledge_questions.stem_locator->>'tex' + question_no
    → knowledge_questions.id (UUID)
```

2026-11-06 实测 6050/6050 命中。**但这是隐式契约**：tex 文件改名/重导入会断链。建议后续 migration 增加：

- `knowledge_questions.external_ref`（唯一，存 qid），或
- 独立映射表 `knowledge_question_external_ids(question_id UUID, source_system, external_id)`。

在补齐前，同步程序必须校验映射 100% 命中并拒绝部分导入（不做模糊匹配）。

---

## 2. 字段所有权：Obsidian 可编辑 vs 只读

### 2.1 Obsidian 侧可编辑（人工审校写入区）

| 位置 | 字段 | 说明 |
| --- | --- | --- |
| 题卡 frontmatter `04_Exams/**/…-qNN.md` | `knowledge_points`、`methods`、`question_type`（题型修正） | 知识点/方法以 kp_id/method_id 表示，由审校人填写 |
| 题卡正文 | `## 答案`、`## 解析` 内容 | 修订答案/解析（正文修订，不是结构字段） |
| 题卡 frontmatter | `quality.ocr_status`、`quality.human_verified`、`human_edited`、`## 校核` checklist | 审校状态与人工结论 |
| 标注文件 `02_Processed/Annotations/gk_*.json` | `annotation.kp_primary`、`kp_secondary`、`rationale`、`status`、`reviewed_by` | 现有标注编辑面；导入 PG 的输入 |
| 知识点卡 `05_KnowledgePoints/**` | 名称、定义、典型例题、反例、备注 | 词表文档性维护（ID 终身不变） |
| 方法卡 `06_Methods`、题型卡 `07_QuestionTypes` | 名称、定义、归类说明 | 文档性维护 |
| `08_Review/**`、`10_Indexes/**` | 审校记录、索引说明 | 人工写作/组织 |
| 任意 md | `## 备注`、人工备注区 | 不进入 PG 结构字段，可同步为 review notes |

### 2.2 Obsidian 侧只读（必须由 PG 决定）

| 字段/内容 | 原因 |
| --- | --- |
| `question_id`(qid)、`document_id`、`question_number`、`ordinal` | 结构主键；改号会在 PG 产生“另一题” |
| 年份、卷别、科类、`source_type`、`title`、来源/许可 | 来源事实，由导入管线维护 |
| 题干原文、`stem_locator`、`answer_locator`、OCR 原文与哈希 | 与原始 PDF/TeX 溯源绑定；重 OCR 不得覆盖人工修订 |
| `checksum_sha256`、`version_no`、`knowledge_document_versions` 状态 | 版本管理字段 |
| PG 生成的索引页/统计页（带 `generated: true` 标记时） | 派生投影，重建会覆盖 |
| `knowledge_annotations.id/superseded_by/created_at` | 数据库内部版本字段 |

### 2.3 PG 侧写入边界

| 写入方 | 允许写的表/字段 |
| --- | --- |
| 导入管线（工具/服务，系统角色） | `sources`、`document_versions`、`chunks`、`questions` 结构字段、`annotations`（model/rule）。**默认不写 `current_knowledge_points`**（旧缓存，见 §6.2）；仅 `--sync-legacy-points` 迁移开关显式开启时才写 |
| 人工审校同步（Obsidian → PG） | `annotations`（由审校产生的行，`classification_source=teacher`、`created_by=reviewer`）、`reviews`；`questions.current_paper_question_type` 由同步程序重算。`current_knowledge_points` 迁移完成前不写 |
| 教师端/前端 API | 走 `knowledge_reviews` 与标注修正接口，不直接 UPDATE 结构字段 |
| Qdrant 写入器 | 只读 PG；不写 PG |

---

## 3. 同步流程

### 3.1 方向 A：Obsidian → PG（审校结果入库）

触发：人工审校提交（或批次同步）。步骤：

1. **收集变更**：比较 vault 文件内容哈希（`synced_hash` 记录在本地同步账本，建议 `var/sync/state.json`）与上次同步值；只处理变化的题卡/标注条目。
2. **校验**：
   - qid 唯一且映射到唯一 PG `question_id`；
   - kp_id 在词表内；`kp_primary` 至多 1 个；`kp_secondary` 有序、去重；
   - 只读字段未变（若变 → 拒绝并提示“请在 PG 侧修正来源信息”）；
   - 修改者/审校时间存在（`reviewed_by` / `reviewed_at`）。
3. **写 PG（单事务）**：
   - 标注变化：旧行 `superseded_by` → 新行；`classification_source=teacher`（人工）或保留 model（模型重标）；`created_by=审校人`；
   - 审校记录：写 `knowledge_reviews`（`review_type='annotation'`、`target_id`、`target_hash`、`decision`、`reviewer_id`、`notes`、`reviewed_at`）；
   - `questions.current_knowledge_points`：**迁移完成前不写**（旧缓存，见 §6.2）；迁移后由 annotations 重算 kp_id 数组；
   - 更新题卡/JSON 的 `synced_at`、`synced_hash`、`human_edited=true`（同步账本）。
4. **写回投影**（方向 B）。
5. **触发下游**：内容哈希变化 → 重建 embedding/Qdrant（见 §5）。

幂等：同一 `(question_id, annotation_type, 内容哈希)` 重复提交必须 no-op；以 `superseded_by IS NULL` 的 active 行做唯一性保障。

### 3.2 方向 B：PG → Obsidian（派生投影）

只投影，不产生新事实：

| 投影目标 | 数据来源 | 说明 |
| --- | --- | --- |
| 题卡 frontmatter `knowledge_points`、`methods` | `knowledge_annotations`(active) | 以 kp_id 数组写回（不读 `current_knowledge_points` 旧缓存） |
| 题卡 `quality.human_verified`、`## 校核` 勾选状态 | `knowledge_reviews` 最新决策 | 仅展示 |
| 模块/年份索引页、统计页（`10_Indexes/**` 中标记 generated 的部分） | 聚合查询 | 全量重建 |
| Qdrant/全文索引 | `chunks` + embeddings | 见 §5 |

**防环规则**：

- 投影文件/字段写入时带 `generated: true` + `generated_hash` + `source_version`；人工不得修改带该标记的字段（改了会在下次同步被覆盖并产生冲突记录）。
- 投影内容不进入方向 A 的变更收集（同步账本对投影文件使用独立命名空间/哈希盐）。
- 若人工确实要修改投影字段（如补知识点），必须改“源字段”（标注 JSON/题卡人工区），由方向 A 落 PG 后再重新投影。

### 3.3 双向时序（推荐）

```
人工审校 (Obsidian)
   → 同步 A：校验 + 写 PG（标注/审校/current_*）+ 记录 hash/version
   → 投影 B：PG 重算题卡知识点/索引（只写 generated 区）
   → 内容哈希变化 → 重建 embedding → 更新 Qdrant / 全文索引
```

任何一步失败：PG 事务回滚；同步账本不推进 hash；下次重试（幂等）。

---

## 4. 冲突规则

### 4.1 判定维度

| 维度 | 来源 | 用途 |
| --- | --- | --- |
| `target_hash` / 内容哈希 | 同步 A 计算，存 `knowledge_reviews.target_hash` 与同步账本 | 判断自上次同步后是否真变（格式/空白变化不算） |
| `version` | `knowledge_annotations` 版本链（superseded_by）+ `knowledge_document_versions.version_no` | 判断谁基于旧版本修改 |
| `last-reviewed` | `knowledge_reviews.reviewed_at`、`annotations.created_at` | 审校时间先后 |

### 4.2 裁决表

| 情形 | 裁决 |
| --- | --- |
| 字段属于 Obsidian 可编辑区，且人工审校更新于上次同步 | **接受 Obsidian 改动**（human wins），写 PG 新版本并保留旧版本链 |
| 字段属于 Obsidian 可编辑区，但 PG 也有更新的审校记录（reviewed_at 更晚） | 以**较晚的人工审校**为准；若同一条 qid+字段两边都改 → 冲突，拒绝自动合并，输出 diff 要求人工裁决 |
| 字段属于 PG 只读区（题号/来源/题干/定位/哈希） | **PG 优先**；Obsidian 改动被拒绝并记录冲突（不允许以“知识点修正”为名改结构） |
| PG 侧模型批量重标 vs Obsidian 人工审校 | 人工（`teacher`）优先；模型重标不得覆盖 teacher 行，须生成新 active 行并把人工作废/并存，按审核流程处理 |
| 投影区被人工修改 | 人工改动不进入源；下次投影覆盖，并记录 conflict（提示“请改源字段”） |
| stale 写入（基于旧 hash） | 拒绝写入，要求先同步最新投影/版本再改 |

### 4.3 冲突记录

每次冲突写 `knowledge_reviews.review_type='sync_conflict'`（若正式表无此枚举则先落 `var/sync/conflicts/*.json`），含：qid、字段、Obsidian 值/哈希、PG 值/版本、时间、处理结论。**冲突不得静默丢弃**。

---

## 5. Qdrant 与派生索引

- Qdrant 存：向量 ID、对应实体 ID（`knowledge_chunks.id` / `knowledge_questions.id`）、embedding、过滤元数据（年份/卷别/source_type/kp_id）。
- **Qdrant 是派生索引**：唯一事实源在 PG（内容）与标准化文件（原始文本）；删除 Qdrant collection 后必须能仅凭 PG 重建。
- 重建流程：`knowledge_chunks`（text_content/text_hash）→ embedding（Qwen3-Embedding-0.6B，模型版本记录）→ upsert Qdrant → 写 `knowledge_indexing_jobs` 指标。
- 触发：chunk 的 `text_hash` 变化、embedding 模型版本变化、投影/标注影响过滤字段时重建对应子集（按实体 ID 删除后重插）。
- 禁止：任何服务从 Qdrant 反写 PG/Obsidian；Qdrant 数据丢失不构成知识库数据丢失。

---

## 6. 字段映射：Obsidian 标注 → `knowledge_annotations`

### 6.1 现有标注 JSON（`02_Processed/Annotations/gk_*.json`）

```json
{"items": [{"question_id": "gk_2016_sichuan_arts_q05",
            "annotation": {"kp_primary": "kp_01_06_sufficient",
                           "kp_secondary": [],
                           "source": "model",
                           "model": "deepseek-flash (batch, 2026-11-05)",
                           "confidence": 0.95,
                           "status": "needs_review",
                           "rationale": "...",
                           "reviewed_by": null}}]}
```

| Obsidian 字段 | PG 目标 | 规则 |
| --- | --- | --- |
| `question_id` | `knowledge_questions.id` | 经 §1.2 映射表转换 UUID；无命中即拒绝 |
| `kp_primary` | `knowledge_annotations` 行：`annotation_type='kp_primary'`, `value=kp_xx_yy_slug` | 每题至多 1 条 active；无 primary 时不落行（无归属题） |
| `kp_secondary[]` | 行：`annotation_type='kp_secondary'`, `value=JSON 数组字符串` | 唯一索引 `(question_id, annotation_type) WHERE superseded_by IS NULL` 只允许一行，故用 JSON 数组保持有序 |
| `source` (model/rule/teacher) | `classification_source` | 库约束只允许 `rule/model/teacher`；**不接受 "import"** |
| `model` | `model_version` | `classification_source='model'` 时必填（库 CHECK） |
| `confidence` | `confidence` | NUMERIC(4,3) |
| `status` | 不落 `knowledge_annotations` | `needs_review` 是审校工作流状态，未来经 `knowledge_reviews`/同步账本承载 |
| `rationale` | 不落表（无列） | 保留在 JSON；如需入库，建议增加 `rationale`/`notes` 列或写 `knowledge_reviews.notes`（open item） |
| `reviewed_by` | `created_by`（人工行）/`knowledge_reviews.reviewer_id` | 模型导入时为 NULL，不冒充人工 |

### 6.2 `knowledge_questions.current_*` 规则（含 2026-11-06 还原事件）

**口径（重要）**：

- **`knowledge_annotations` 是 kp_id 的唯一事实源**（`kp_primary` / `kp_secondary`，带版本链）。
- **`current_knowledge_points` 是旧工作台遗留的中文模块名缓存**（如 `三角函数/集合与逻辑`），**不是新事实源**；迁移评审完成前保持旧语义（非空 4748/6050、NULL 1302）。
- **hybrid retrieval 必须读 `knowledge_annotations`**（active 行），不得依赖 `current_knowledge_points` 的中文名或 kp_id 格式。

**为什么这样定**：旧 `backend/app/tools/impl.py::knowledge_search` 用
`current_knowledge_points && CAST(:topic_points AS text[])`（中文模块名）做过滤，
26.7%（4/15）旧基线依赖该语义。2026-11-06 首次标注导入曾把该列改成 kp_id 数组，
导致过滤永不匹配、旧基线不可复现；同日已用导入前快照
`var/annotations/old_current_knowledge_points.tsv` 还原 6050 题（逐条与快照一致，
`knowledge_annotations` 保持 8007 条 active 不变），复跑
`tools/eval_retrieval.py --k 8 --out-prefix var/retrieval/legacy_repro`
得到 Recall@8 = 4/15 = **26.7%**、MRR 0.180，与 `var/retrieval/baseline_2026-11-06.json` 一致。

**写入规则**：

- 标注导入工具 `tools/kb_annotations_to_pg.py` **默认只写 `knowledge_annotations`**，不碰该列；
- 仅当显式 `--sync-legacy-points`（迁移评审通过、检索/UI 已适配后）才把该列重算为
  active `kp_primary` + `kp_secondary` 的 kp_id 数组（primary 在首位，secondary 按 JSON 顺序；无标注 → NULL）；
- 迁移完成后：该列由 annotations 投影重算，旧中文名缓存退役，旧基线改用新口径重测；
- 任何其它写入视为违约。

### 6.3 题卡（Markdown frontmatter/正文）→ PG

| 题卡字段 | PG 目标 | 说明 |
| --- | --- | --- |
| `question_id` / `document_id` / `question_number` | `knowledge_questions`（只读校验） | 不允许改 |
| `question_type` | `current_paper_question_type`（映射 single_choice/multiple_choice/fill_blank/free_response） | 人工可修正题型 → 写投影 |
| `knowledge_points` / `methods` | `annotations`（teacher 行） | 与标注 JSON 同一目标，冲突时以较新审校为准 |
| `## 答案` / `## 解析` 正文 | 目标表**尚未定义**（当前答案在 `knowledge_chunks` 的 answer chunk + `answer_locator`） | 人工修订答案需要版本化存储（建议新增 `knowledge_answer_revisions` 或 `reviews` 扩展）；**open item** |
| `quality.human_verified` / `## 校核` | `knowledge_reviews`（review_type='question_card'） | 只记录审校结论，不改答案内容 |
| `human_edited` | 同步账本必填 | 为 true 时禁止自动重 OCR/重导入覆盖 |

---

## 7. 同步账本（建议新增，尚未实现）

建议文件 `var/sync/state.json`（不入库，仅本地/CI 状态）：

```json
{"entity": "question:gk_2016_sichuan_arts_q05",
 "obsidian_hash": "sha256:...",
 "pg_version": 12,
 "last_synced_at": "2026-11-06T13:00:00+08:00",
 "last_synced_by": "teacher:uuid",
 "direction": "obsidian_to_pg",
 "status": "ok"}
```

规则：hash 一致 → 跳过；`pg_version` 落后 → 允许写；冲突 → 记录并阻止。账本丢失时可从 `knowledge_reviews.target_hash` + 文件哈希重建（允许重复导入，导入幂等）。

---

## 8. 权限与安全

- `knowledge_*` 表启用 FORCE RLS：平台行写入需要 superuser/BYPASSRLS 角色（导入工具当前以容器内 `postgres` 执行）；教师写入走 `scope='teacher'` 策略 + `app_current_user_id()`。
- 数据库密码只存在于容器 env（`POSTGRES_PASSWORD`），工具通过 `docker exec ... PGPASSWORD="$POSTGRES_PASSWORD"` 使用，**不落文件、不打印、不进 SQL 快照**。
- 同步账本、冲突文件、SQL 快照不含凭证。

---

## 9. 当前落地状态（2026-11-06）

| 项 | 状态 |
| --- | --- |
| Obsidian 标注 → PG `knowledge_annotations` | ✅ 已实现：`tools/kb_annotations_to_pg.py`；274 文件 / 6050 条；写入 8007 条 active（primary 6045 + secondary 1962）；幂等复跑 0 变化 |
| `current_knowledge_points` | ⚠️ **旧工作台中文模块名缓存，已还原（task-14）**：非空 4748 / NULL 1302，逐条与导入前快照一致；导入工具默认不再写该列；旧基线 Recall@8 26.7%（4/15）已复现。kp_id SSOT 在 `knowledge_annotations`，hybrid 必须读 annotations |
| qid → PG UUID 映射 | ⚠️ 派生映射 6050/6050；缺原生外键（open item） |
| Obsidian 审校 → PG（方向 A，人工字段） | ❌ 未实现（本次只导入模型标注） |
| PG → Obsidian 投影（方向 B） | ❌ 未实现（题卡 knowledge_points 等尚未回写） |
| 冲突处理 / 同步账本 | ❌ 未实现（规则已定义，见 §4/§7） |
| Qdrant 重建 | ❌ 未实现（索引层尚未接入；注意 PG 中 `knowledge_indexing_jobs`=0） |
| 报告 | `var/annotations/import_report.md`（计数/校验/遗留缓存与还原记录/风险）、`var/annotations/verify_after_apply.txt`（独立逐条复核）、`var/annotations/restore_legacy_points_console.txt`（还原验证） |

## 10. Open items（需决策）

1. **qid 外键**：给 `knowledge_questions` 加 `external_ref`（qid）或映射表（推荐，迁移 + 回填脚本）。
2. **5 题无归属**：人工补 primary 或扩充词表（图论/优选法/数学文化/题干缺失），补齐后重跑导入即可。
3. **`current_knowledge_points` 遗留缓存退役**：迁移前保持旧中文语义（旧 `knowledge_search`/26.7% 基线依赖）；hybrid retrieval 改用 `knowledge_annotations`；待检索/UI/评测口径全部适配后，用 `--sync-legacy-points` 切换为 kp_id 投影并重测基线，再删除旧缓存语义。
4. **答案/解析修订的版本化存储**：新增表或扩展 `knowledge_reviews`，否则 Obsidian 修订无法进 PG。
5. **`rationale`/`status` 字段**：是否给 `knowledge_annotations` 增列，或统一放 `knowledge_reviews.notes`。
6. **stale 标注删除策略**：源删除 → PG active 行如何 tombstone（当前工具只报告）。
7. **投影标记规范**：`generated: true` + hash 的字段级清单与时序。
8. **Qdrant 重建作业**：embedding 模型版本、增量触发条件、索引任务记录规范。

---

## 11. 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-11-06 | v0.1 | 草案建立：SSOT 边界、字段所有权、双向同步、冲突规则、标注映射、Qdrant 派生定位；记录首次标注导入落地状态与 open items |
| 2026-11-06 | v0.2 | 修正 `current_knowledge_points` 定位：明确定义为**旧工作台遗留中文模块名缓存（非 SSOT）**；记录 task-13 误改导致旧 knowledge_search/26.7% 基线失效、task-14 用快照还原 6050 题并复现 Recall@8 4/15=26.7%；导入工具默认只写 `knowledge_annotations`，`--sync-legacy-points` 仅迁移评审后使用；hybrid retrieval 必须读 `knowledge_annotations` |
