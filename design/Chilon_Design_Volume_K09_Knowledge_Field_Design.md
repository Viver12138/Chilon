# Chilon 模块分册 K09：知识库字段级设计

> **文档类型**：模块设计分册（Module Volume）
> **分册编号**：K09
> **整理日期**：2026-11-04
> **状态**：**DESIGNED**（Registry 输入草稿，字段冻结前需通过 Schema Freeze Gate）
> **上游基线**：主文档 §14、§26；D.12 / D.13 / D.14；D5 §3.1
> **用途**：把 K009 的 13 张表说到字段级，作为 Phase 1 Registry 的直接输入。

[//]: # (toc:start)
## 目录

- [0. 本册定位](#0-本册定位)
- [1. 通用约定](#1-通用约定)
- [2. 实体关系](#2-实体关系)
- [3. 表设计](#3-表设计)
- [4. RLS 要点](#4-rls-要点)
- [5. 迁移依赖顺序](#5-迁移依赖顺序)
- [6. 查询模式与索引对照](#6-查询模式与索引对照)
- [7. 未决项](#7-未决项)
- [8. 与主文档的对应](#8-与主文档的对应)

[//]: # (toc:end)

---

## 0. 本册定位

### 0.1 本册解决什么

主文档 §14 定了 K009 的结构（两层知识库、题目级单元、派生标注分离），但没定字段。本册给出：

| 内容 | 用途 |
| --- | --- |
| 13 张表的字段、类型、可空、默认、约束 | Registry 字段字典的输入 |
| 索引与查询模式 | 性能与 Registry 索引登记 |
| RLS 要点 | 平台层与教师层共存 |
| 迁移依赖顺序 | Phase 2 建表顺序 |

### 0.2 本册不做什么

- 不生成 DDL。正式 DDL 由 Registry + Generator 产出，本册只是输入草稿。
- 不定义 API 形状（见 D5）。
- 不定义解析器、embedding 模型的具体实现。
- 不定义 K009 之外的表。

### 0.3 状态说明

字段级冻结必须通过 Schema Freeze Gate：字段类型、约束、FK、索引、RLS、权限全部通过才可标 `confirmed`。本册标 `DESIGNED`，表示“可以据此评审与生成 Registry”，不等于已冻结。

------------------------------------------------------------------------

## 1. 通用约定

| 项 | 规则 |
| --- | --- |
| 主键 | `id UUID`，应用层生成 UUIDv7 |
| 时间 | `TIMESTAMPTZ`，UTC；业务日期用 `DATE` |
| 归属 | 教师数据用 `owner_id` 复合 FK；平台数据 `owner_id IS NULL` |
| 软删除 | 仅 `knowledge_sources` 使用 `deleted_at`；其余靠生命周期状态 |
| 精确数值 | 分值、置信度用 `NUMERIC`，不用浮点 |
| JSONB | 只用于定位、过滤条件、指标等确有柔性需求的结构，并带版本 |
| 命名 | snake_case；表名复数；外键 `<实体>_id` |

### 1.1 两层知识库的存储表达

**不用两张表，用一列 `scope` 加一条约束**：

```sql
CHECK (
  (scope = 'platform' AND owner_id IS NULL) OR
  (scope = 'teacher'  AND owner_id IS NOT NULL)
)
```

理由：平台层与教师层的字段完全相同，只有归属与权利默认值不同；拆表会让每个查询都要 UNION，且题目、chunk、检索结果都要跟着分表。

### 1.2 原文事实与派生标注

按 D.13 的结论，字段分两类：

| 类别 | 落在哪里 | 可否被教师修改 | 可否作引用证据 |
| --- | --- | --- | --- |
| 原文事实 | `knowledge_document_versions`、`knowledge_chunks`、`knowledge_questions` 的定位与题号字段 | 只能重新解析 | **可以** |
| 派生标注 | `knowledge_annotations`、`knowledge_question_embeddings` | 可以，且保留历史 | **不可以** |

`knowledge_questions` 上的 `current_paper_question_type` 等 `current_*` 列是**派生标注的查询缓存**，用于过滤与排序；权威值在 `knowledge_annotations`。

------------------------------------------------------------------------

## 2. 实体关系

```text
knowledge_categories 1 ── n knowledge_sources
knowledge_sources    1 ── n knowledge_document_versions
knowledge_document_versions 1 ── n knowledge_chunks
knowledge_document_versions 1 ── n knowledge_questions
knowledge_questions  1 ── n knowledge_annotations
knowledge_questions  1 ── n knowledge_question_embeddings

knowledge_document_versions 1 ── n knowledge_ingestion_runs
knowledge_document_versions 1 ── n knowledge_reviews
knowledge_document_versions 1 ── n knowledge_indexing_jobs
knowledge_retrieval_runs     1 ── n knowledge_retrieval_results

material_versions 1 ── n material_knowledge_citations
```

------------------------------------------------------------------------

## 3. 表设计

### 3.1 `knowledge_categories` 分类

**用途**：分类树。平台提供四个默认分类，教师可新建私有分类。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `scope` | TEXT | 否 | — | `platform` / `teacher` |
| `owner_id` | UUID | 是 | NULL | 教师分类必填，平台分类为 NULL |
| `parent_id` | UUID | 是 | NULL | 上级分类，支持两级 |
| `key` | VARCHAR(64) | 否 | — | 稳定标识，如 `pep_math_textbook` |
| `name` | VARCHAR(120) | 否 | — | 显示名，如“人教版数学教材” |
| `source_type` | TEXT | 是 | NULL | 映射的来源类型；自定义分类可为 NULL |
| `sort_order` | SMALLINT | 否 | 0 | 展示顺序 |
| `is_system` | BOOLEAN | 否 | false | 平台内置分类为 true，不可删改 |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：

- `UNIQUE (scope, owner_id, key)`：同一归属下 key 唯一。
- `CHECK ((scope='platform' AND owner_id IS NULL) OR (scope='teacher' AND owner_id IS NOT NULL))`。
- `source_type` 限定为 `textbook` / `workbook` / `gaokao_paper` / `mock_exam` / `other`。
- `is_system = true` 时禁止 UPDATE `key` 与 DELETE（服务层 + Trigger）。

**四个默认分类**：

| key | name | source_type |
| --- | --- | --- |
| `pep_math_textbook` | 人教版数学教材 | `textbook` |
| `workbook` | 辅导书 | `workbook` |
| `gaokao` | 高考题 | `gaokao_paper` |
| `mock_exam` | 模拟题 | `mock_exam` |

**索引**：`(scope, owner_id, sort_order)`；`(parent_id)`。

---

### 3.2 `knowledge_sources` 来源

**用途**：来源身份与归属。一本书、一套卷子就是一条。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `scope` | TEXT | 否 | — | `platform` / `teacher` |
| `owner_id` | UUID | 是 | NULL | 教师来源必填 |
| `category_id` | UUID | 否 | — | FK → `knowledge_categories` |
| `source_type` | TEXT | 否 | — | `textbook` / `workbook` / `gaokao_paper` / `mock_exam` / `other` |
| `title` | VARCHAR(500) | 否 | — | 书名或卷名 |
| `publisher` | VARCHAR(300) | 是 | NULL | 出版社；教材/教辅必填 |
| `edition` | VARCHAR(200) | 是 | NULL | 版次；教材/教辅必填 |
| `year` | SMALLINT | 是 | NULL | 年份；高考/模拟卷必填 |
| `region` | VARCHAR(100) | 是 | NULL | 地区；高考/模拟卷必填 |
| `paper_name` | VARCHAR(200) | 是 | NULL | 试卷名；高考/模拟卷必填 |
| `language` | VARCHAR(20) | 否 | `zh-CN` | |
| `rights_status` | TEXT | 否 | — | `unverified` / `teacher_confirmed` / `licensed` / `restricted` |
| `distribution_scope` | TEXT | 否 | `private_teacher` | `private_teacher` / `classroom` / `public` |
| `derived_from_source_id` | UUID | 是 | NULL | 教师复制平台来源时指向原来源 |
| `metadata` | JSONB | 否 | `{}` | 非核心扩展；带 `schema_version` |
| `created_by` | UUID | 否 | — | |
| `created_at` | TIMESTAMPTZ | 否 | now() | |
| `updated_at` | TIMESTAMPTZ | 否 | now() | |
| `deleted_at` | TIMESTAMPTZ | 是 | NULL | 软删除 |

**约束**：

- `CHECK ((scope='platform' AND owner_id IS NULL) OR (scope='teacher' AND owner_id IS NOT NULL))`。
- **平台来源 `rights_status` 必须为 `licensed`，`distribution_scope` 必须为 `classroom`**（由 §14.1.2 的 A 档决定，落地为 CHECK 或 Trigger）。
- 教师来源默认 `unverified` + `private_teacher`。
- `(source_type, 必填元数据)` 的一致性由服务层校验：`textbook`/`workbook` 需要 `publisher` + `edition`；`gaokao_paper`/`mock_exam` 需要 `year` + `region` + `paper_name`。
- 删除受 Citation 保留约束（§21.1.5）：有引用的来源只能 `withdrawn`，不能物理删除。

**索引**：`(scope, category_id, source_type)`；`(owner_id, source_type)`；`(deleted_at) WHERE deleted_at IS NULL`。

---

### 3.3 `knowledge_document_versions` 文件版本

**用途**：一份来源可以有多个版本（新版教材、勘误版）。解析、审核、索引都挂在版本上。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `source_id` | UUID | 否 | — | FK → `knowledge_sources` |
| `version_no` | INTEGER | 否 | — | 同一来源内递增 |
| `storage_key` | VARCHAR(500) | 否 | — | Object Storage Key |
| `checksum_sha256` | CHAR(64) | 否 | — | 文件 Hash，lowercase hex |
| `mime_type` | VARCHAR(120) | 否 | — | |
| `file_size_bytes` | BIGINT | 否 | — | |
| `page_count` | INTEGER | 是 | NULL | 解析后可得 |
| `parser_version` | VARCHAR(64) | 是 | NULL | 解析器版本 |
| `parse_schema_version` | VARCHAR(20) | 是 | NULL | 解析产物 Schema 版本 |
| `lifecycle_status` | TEXT | 否 | `processing` | 见下 |
| `submitted_at` | TIMESTAMPTZ | 是 | NULL | 提交审核时间 |
| `approved_at` | TIMESTAMPTZ | 是 | NULL | |
| `indexed_at` | TIMESTAMPTZ | 是 | NULL | |
| `withdrawn_at` | TIMESTAMPTZ | 是 | NULL | |
| `uploaded_by` | UUID | 否 | — | |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**生命周期**（§21.1.5）：

```text
processing → pending_review → approved → indexed
     ↓              ↓
  failed        rejected
  quarantined
任意状态 → withdrawn（已被引用的来源）
         → deleted（无引用且通过清理流程）
```

**约束**：`UNIQUE (source_id, version_no)`；`lifecycle_status` 限定枚举。

**只有 `approved` + `indexed` + 未撤回** 的版本可参与检索与生成 Citation。

**索引**：`(source_id, version_no DESC)`；`(lifecycle_status)`。

---

### 3.4 `knowledge_chunks` 文本块

**用途**：Citation 的定位单元。题目由若干 chunk 组成。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `document_version_id` | UUID | 否 | — | FK |
| `chunk_key` | VARCHAR(200) | 否 | — | 解析器产出的稳定键 |
| `ordinal` | INTEGER | 否 | — | 文档内顺序 |
| `text_content` | TEXT | 否 | — | 规范化后的文本 |
| `text_hash` | CHAR(64) | 否 | — | `text_content` 的 SHA-256 |
| `locator` | JSONB | 否 | — | 页码、字符区间、bbox |
| `content_kind` | TEXT | 否 | `text` | `text` / `formula` / `table` / `figure` |
| `parser_version` | VARCHAR(64) | 否 | — | |
| `parse_schema_version` | VARCHAR(20) | 否 | — | |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：`UNIQUE (document_version_id, parser_version, parse_schema_version, chunk_key)`——这是 §14.5 里“重复解析产生唯一键冲突”的解法：把解析器版本纳入唯一域，升级解析器产生新 chunk 而不覆盖旧 chunk。

**索引**：`(document_version_id, ordinal)`。

---

### 3.5 `knowledge_questions` 题目单元

**用途**：检索与引用的最小单位。一张试卷切分成 N 道题。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `document_version_id` | UUID | 否 | — | FK |
| `question_no` | VARCHAR(32) | 否 | — | 卷面题号，如 `12`、`18(1)` |
| `section_label` | VARCHAR(120) | 是 | NULL | 卷面分区，如“第 II 卷 解答题” |
| `ordinal` | INTEGER | 否 | — | 卷内顺序 |
| `stem_locator` | JSONB | 否 | — | 题干定位；单段或 `segments` |
| `answer_locator` | JSONB | 是 | NULL | 答案定位；答案另有册时为独立区段 |
| `score` | NUMERIC(5,2) | 是 | NULL | 分值 |
| `segmentation_status` | TEXT | 否 | `auto` | `auto` / `accepted` / `corrected` / `rejected` |
| `segmentation_source` | TEXT | 否 | `rule` | `rule` / `model` / `teacher` |
| `current_paper_question_type` | TEXT | 否 | — | 派生缓存：`single_choice` / `multiple_choice` / `fill_blank` / `free_response` |
| `current_knowledge_points` | TEXT[] | 是 | NULL | 派生缓存：知识点标签 |
| `created_at` | TIMESTAMPTZ | 否 | now() | |
| `updated_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：

- `UNIQUE (document_version_id, question_no)`。
- `current_paper_question_type` 限定四值（D.14）。
- `score` 建议 `CHECK (score >= 0)`。

**为什么用 JSONB 存定位而不是建题目-块关联表**：题目与 chunk 是 1:N 且需要**跨页多段**定位，`segments` 天然是多段结构；建关联表要多一张表并处理顺序与角色，收益不足以抵消复杂度。代价是定位不能走关系查询——但定位只用于引用回溯，不用于筛选。**此决定标注为可复议**：若后续需要按“题干所在章节”检索，再引入关联表。

**索引**：

- `(document_version_id, ordinal)`
- `(current_paper_question_type)`
- `(segmentation_status) WHERE segmentation_status <> 'accepted'`

---

### 3.6 `knowledge_annotations` 派生标注

**用途**：题型、知识点、难度等**由规则或模型产出、可被教师修正**的标注。带版本，不覆盖历史。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `question_id` | UUID | 否 | — | FK |
| `annotation_type` | TEXT | 否 | — | `paper_question_type` / `knowledge_point` / `difficulty` / `other` |
| `value` | TEXT | 否 | — | 标注值（题型枚举、知识点名等） |
| `classification_source` | TEXT | 否 | — | `rule` / `model` / `teacher` |
| `confidence` | NUMERIC(4,3) | 是 | NULL | 0–1；规则产出可为 1 |
| `model_version` | VARCHAR(120) | 是 | NULL | 模型标注时必填 |
| `superseded_by` | UUID | 是 | NULL | 指向取代它的新标注 |
| `created_by` | UUID | 是 | NULL | 教师修正时记录 |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：

- 同一 `(question_id, annotation_type, value)` 只允许一条“当前有效”记录：
  `CREATE UNIQUE INDEX ... ON knowledge_annotations (question_id, annotation_type, value) WHERE superseded_by IS NULL`。
- 修正时不 UPDATE，而是插入新记录并回填旧记录的 `superseded_by`。
- `classification_source = 'model'` 时 `model_version` 必填。

**为什么不用 `question` 上的列直接存**：教师修正必须留痕，且模型重跑不能覆盖教师结论。`current_*` 缓存列由服务层在标注变更时同步刷新。

**索引**：`(question_id, annotation_type) WHERE superseded_by IS NULL`。

---

### 3.7 `knowledge_question_embeddings` 向量

**用途**：派生数据，用于题型分类辅助与后续检索升级。可随时重建。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `question_id` | UUID | 否 | — | FK |
| `model` | VARCHAR(120) | 否 | — | 如 `bge-m3` |
| `dim` | SMALLINT | 否 | — | 维度 |
| `embedding` | VECTOR | 否 | — | pgvector；维度按模型定 |
| `content_hash` | CHAR(64) | 否 | — | 被嵌入文本的 Hash，用于判断是否需重建 |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：`UNIQUE (question_id, model)`。

**重建规则**：`content_hash` 与当前题目文本 Hash 不一致时视为过期，由重建任务覆盖。

**注意**：向量**不作为检索主路径**（D.13），MVP 检索走关键词 + 元数据。pgvector 扩展需在 Registry 中登记为可选依赖。

---

### 3.8 `knowledge_ingestion_runs` 处理记录

**用途**：上传、扫描、解析、切分、分类、索引各阶段的执行记录，用于排障与审计。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `document_version_id` | UUID | 否 | — | FK |
| `stage` | TEXT | 否 | — | `scan` / `parse` / `ocr` / `segment` / `classify` / `index` |
| `status` | TEXT | 否 | — | `running` / `succeeded` / `failed` / `cancelled` |
| `tool_version` | VARCHAR(120) | 是 | NULL | |
| `started_at` | TIMESTAMPTZ | 否 | — | |
| `finished_at` | TIMESTAMPTZ | 是 | NULL | |
| `error_code` | VARCHAR(80) | 是 | NULL | |
| `error_detail` | TEXT | 是 | NULL | 不得含原文内容 |
| `metrics` | JSONB | 是 | NULL | 耗时、页数、题目数等 |

**索引**：`(document_version_id, stage, started_at DESC)`。

---

### 3.9 `knowledge_reviews` 审核记录

**用途**：教师审核证据。四类审核共表：来源审核、切分校对、标注修正、权利确认。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `document_version_id` | UUID | 否 | — | FK |
| `review_type` | TEXT | 否 | — | `source_approval` / `segmentation` / `annotation` / `rights` |
| `target_id` | UUID | 是 | NULL | 细分目标，如具体 question_id |
| `decision` | TEXT | 否 | — | `approved` / `rejected` / `needs_changes` |
| `target_hash` | CHAR(64) | 是 | NULL | 审核时锁定内容的 Hash |
| `reviewer_id` | UUID | 否 | — | |
| `notes` | TEXT | 是 | NULL | 拒绝或修改时必填 |
| `reviewed_at` | TIMESTAMPTZ | 否 | now() | |

**不变量**：审核绑定 `target_hash`；内容变化后旧审核自动失效（与 Draft 的 fresh 语义一致）。

**索引**：`(document_version_id, review_type)`；`(target_id)`。

---

### 3.10 `knowledge_indexing_jobs` 索引任务

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `document_version_id` | UUID | 否 | — | FK |
| `job_type` | TEXT | 否 | — | `keyword` / `embedding` / `full_rebuild` |
| `status` | TEXT | 否 | — | `queued` / `running` / `succeeded` / `failed` / `cancelled` |
| `scheduled_at` | TIMESTAMPTZ | 否 | now() | |
| `started_at` | TIMESTAMPTZ | 是 | NULL | |
| `finished_at` | TIMESTAMPTZ | 是 | NULL | |
| `attempt` | SMALLINT | 否 | 0 | |
| `error_code` | VARCHAR(80) | 是 | NULL | |

**索引**：`(status, scheduled_at) WHERE status IN ('queued','running')`——队列轮询用。

---

### 3.11 `knowledge_retrieval_runs` 检索运行

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `owner_id` | UUID | 否 | — | 发起检索的教师 |
| `query_text` | TEXT | 是 | NULL | 原始查询；不得含个人敏感信息 |
| `query_hash` | CHAR(64) | 否 | — | 用于 Citation 的 `query_hash` |
| `filters` | JSONB | 是 | NULL | 分类、卷面题型、年份、scope |
| `top_k` | SMALLINT | 否 | 20 | |
| `result_count` | INTEGER | 是 | NULL | |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**索引**：`(owner_id, created_at DESC)`。

---

### 3.12 `knowledge_retrieval_results` 检索结果

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `retrieval_run_id` | UUID | 否 | — | FK |
| `question_id` | UUID | 否 | — | FK → `knowledge_questions` |
| `rank` | SMALLINT | 否 | — | 1 起 |
| `score` | NUMERIC(8,4) | 是 | NULL | 相关性分；关键词检索可为 NULL |
| `matched_chunk_id` | UUID | 是 | NULL | 命中的具体块，用于高亮 |

**约束**：`UNIQUE (retrieval_run_id, question_id)`。

**作用**：Citation Snapshot 要固定 `retrieval_run_id` 与 `retrieval_result_id`，证明“这条引用确实来自一次检索”。

---

### 3.13 `material_knowledge_citations` 引用投影

**用途**：发布时从 AST 的 Citation Snapshot 固化，形成可查询的 Material × 节点 × 来源投影。

| 字段 | 类型 | 空 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | UUID | 否 | — | 主键 |
| `material_version_id` | UUID | 否 | — | FK → K012 |
| `content_node_id` | UUID | 否 | — | AST 节点 ID |
| `citation_id` | UUID | 否 | — | AST 内 Citation ID |
| `source_id` | UUID | 否 | — | |
| `document_version_id` | UUID | 否 | — | |
| `question_id` | UUID | 是 | NULL | 引用的具体题目；非题目引用为 NULL |
| `chunk_id` | UUID | 否 | — | |
| `excerpt_hash` | CHAR(64) | 否 | — | 与 Citation Snapshot 一致 |
| `rights_status_snapshot` | TEXT | 否 | — | 发布时的权利状态 |
| `distribution_scope_snapshot` | TEXT | 否 | — | 发布时的分发范围 |
| `created_at` | TIMESTAMPTZ | 否 | now() | |

**约束**：`UNIQUE (material_version_id, citation_id)`。

**不变量**：投影只能从不可变 AST 重建；不得在投影中引入 AST 之外的来源或修改 Excerpt。

**索引**：`(material_version_id)`；`(source_id)`；`(question_id) WHERE question_id IS NOT NULL`。

------------------------------------------------------------------------

## 4. RLS 要点

### 4.1 读取

```sql
-- 平台来源对全体教师可见；教师来源仅本人可见
USING (
  scope = 'platform'
  OR owner_id = public.app_current_user_id()
)
```

**平台行没有 `owner_id`**，所以不能用 `owner_id = current_user()` 单条策略，必须显式区分两层。

### 4.2 写入

| 角色 | 可写 |
| --- | --- |
| `chilon_system_worker` | 平台层全部表（导入、解析、索引） |
| `chilon_app` | 教师层来源、草稿相关；不能写平台层 |
| 教师 | 通过服务层，不直连数据库 |

平台来源的解析产物（chunk / question / annotation）由系统 Worker 写入，教师只能通过 `POST .../segments` 与 `.../annotations` 产生修正记录——**修正写入的是教师层标注，不改平台原文**。

### 4.3 跨层引用

教师生成的 Material 可以引用平台来源，此时 `material_knowledge_citations` 记的是平台层的 `source_id`。该表按 `material_version_id` 的 Owner 隔离，不按来源层隔离。

------------------------------------------------------------------------

## 5. 迁移依赖顺序

```text
1. knowledge_categories            （无外部依赖）
2. knowledge_sources               （→ categories）
3. knowledge_document_versions     （→ sources）
4. knowledge_chunks                （→ document_versions）
5. knowledge_questions             （→ document_versions）
6. knowledge_annotations           （→ questions）
7. knowledge_question_embeddings   （→ questions；需 pgvector）
8. knowledge_ingestion_runs        （→ document_versions）
9. knowledge_reviews               （→ document_versions）
10. knowledge_indexing_jobs        （→ document_versions）
11. knowledge_retrieval_runs       （→ owner）
12. knowledge_retrieval_results    （→ runs, questions）
13. material_knowledge_citations   （→ K012 material_versions）
```

`material_knowledge_citations` 依赖 K012 建表，必须在 K012 之后。

------------------------------------------------------------------------

## 6. 查询模式与索引对照

| 查询 | 索引 |
| --- | --- |
| 按分类取题目 | `questions` × `document_version` × `sources(category_id)` 需复合规划，见 §7 未决项 |
| 按卷面题型筛选 | `questions(current_paper_question_type)` |
| 取某试卷的全部题目 | `questions(document_version_id, ordinal)` |
| 取某题的有效标注 | `annotations(question_id, annotation_type) WHERE superseded_by IS NULL` |
| 队列轮询 | `indexing_jobs(status, scheduled_at) WHERE status IN (...)` |
| 检索历史 | `retrieval_runs(owner_id, created_at DESC)` |

------------------------------------------------------------------------

## 7. 未决项

| # | 问题 | 影响 | 归属 |
| --- | --- | --- | --- |
| 1 | 按分类筛题需要跨 `questions → document_versions → sources` 三跳，是否在 questions 上冗余 `category_id` 与 `scope` | 检索性能 | Registry 设计时决定 |
| 2 | `stem_locator` 用 JSONB 是否够用；是否需要题目-块关联表 | 定位与检索的灵活性 | 首次实现后评估 |
| 3 | pgvector 维度需按选定模型定；扩展登记为可选依赖 | 部署 | 选型后冻结 |
| 4 | 知识点体系（`current_knowledge_points`）是自由文本还是受控词表 | 检索质量与统计 | 需与产品确认 |
| 5 | `score` 与分值的统计用途是否进入门户 | 报表 | 第二批 |
| 6 | 平台层导入的批量事务与失败回滚粒度 | 导入可靠性 | Phase 2 |

------------------------------------------------------------------------

## 8. 与主文档的对应

| 主文档位置 | 本册对应 |
| --- | --- |
| §14.1 两层知识库 | §1.1、§4 |
| §14.2 十三张表 | §3 全表 |
| §14.4.1 题目级切分 | §3.5 |
| §14.4.2 派生标注边界 | §1.2、§3.6 |
| §14.4.3 卷面题型 | §3.5 `current_paper_question_type` |
| D.15 跨段定位 | §3.5 `stem_locator` / `answer_locator` |
| D5 §3.1 知识库接口 | §6 查询模式 |

------------------------------------------------------------------------

**分册结束**

本册是 Registry 的输入，不是最终 DDL。字段冻结以 Schema Freeze Gate 的结论为准；任何字段变更需同步更新主文档 §14 与 `schemas/` 下的相关契约。
