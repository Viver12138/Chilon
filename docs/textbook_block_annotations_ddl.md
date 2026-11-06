# 教材块标注表 DDL（textbook_block_annotations）

> 状态：draft schema + data applied；不调 OCR、不写 mock/gaokao/knowledge_annotations、不 commit。  
> 输入：`var/textbook_mapping/mapped_1797_reviewed.json`（1797 条，360 teacher / 1437 model）。

## 1. 设计目标

- **chunk 级**：一条 active 标注对应一个 `knowledge_chunks.id`；教材块 `block_id` 保留为业务稳定 ID。
- **teacher/model 双状态**：`classification_source` 区分 `model`/`teacher`；`review_status` 区分 `needs_review`/`reviewed`，历史不覆盖。
- **唯一 active**：同一 chunk 只能有一条 `superseded_by IS NULL` 的标注；新版本通过 `superseded_by` 指向旧版本。
- **RLS**：通过 `chunk_id → knowledge_chunks → knowledge_document_versions → knowledge_sources.owner_id` 复用知识库的 owner 边界。
- **可回滚**：`superseded_by` 自 FK + active 唯一索引；数据层回滚可删本表数据，schema 层回滚可回退 migration。

## 2. Registry/generator 取舍

采用 **registry-first**，没有走独立 migration 的 fallback：

| 文件 | 变更 |
| --- | --- |
| `database/registry/fields/k009.json` | 新增表定义、字段、check、index、RLS policy |
| `database/registry/schema.json` | `tables` + `table_order` 加入新表 |
| `database/generated/schema.sql` | 由 generator 重新生成 |
| `database/generated/manifest.json` | 由 generator 重新生成 |
| `backend/migrations/versions/0002_textbook_block_annotations.py` | 由 `gen_migration.py` 生成的新 revision |

取舍说明：registry 改动只涉及 K009 的一个 detail 表，generator/validator 已验证通过，成本低于维护独立 migration；因此优先 registry，避免表结构脱离权威 registry。当前数据库由既有 schema 初始化，本任务只从 generated DDL 抽取本表语句执行，不跑全量 `alembic upgrade`，避免重复建既有表。

## 3. DDL

```sql
CREATE TABLE textbook_block_annotations (
    "id" UUID NOT NULL,
    "chunk_id" UUID NOT NULL,
    "block_id" VARCHAR(80) NOT NULL,
    "kp_primary" TEXT,
    "kp_secondary" JSONB NOT NULL DEFAULT '[]'::jsonb,
    "module_id" VARCHAR(40),
    "status" VARCHAR(16) NOT NULL,
    "classification_source" VARCHAR(16) NOT NULL,
    "confidence" NUMERIC(4,3),
    "model_version" VARCHAR(120),
    "review_status" VARCHAR(16) NOT NULL,
    "rationale" TEXT,
    "superseded_by" UUID,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_textbook_block_annotations PRIMARY KEY ("id"),
    CONSTRAINT fk_textbook_block_annotations_chunk_id FOREIGN KEY ("chunk_id") REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
    CONSTRAINT fk_textbook_block_annotations_superseded_by FOREIGN KEY ("superseded_by") REFERENCES textbook_block_annotations(id) ON DELETE RESTRICT,
    CONSTRAINT ck_textbook_block_annotations_status CHECK (status IN ('mapped','non_content','vocab_gap')),
    CONSTRAINT ck_textbook_block_annotations_source CHECK (classification_source IN ('rule','model','teacher')),
    CONSTRAINT ck_textbook_block_annotations_review CHECK (review_status IN ('draft','needs_review','reviewed','rejected')),
    CONSTRAINT ck_textbook_block_annotations_conf CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_textbook_block_annotations_model_version CHECK (classification_source <> 'model' OR model_version IS NOT NULL)
);

ALTER TABLE textbook_block_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE textbook_block_annotations FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_textbook_block_annotations_owner ON textbook_block_annotations FOR ALL USING (
    EXISTS (
        SELECT 1 FROM knowledge_chunks
        JOIN knowledge_document_versions ON knowledge_document_versions.id = knowledge_chunks.document_version_id
        JOIN knowledge_sources ON knowledge_sources.id = knowledge_document_versions.source_id
        WHERE knowledge_chunks.id = chunk_id AND knowledge_sources.owner_id = public.app_current_user_id()
    )
) WITH CHECK (
    EXISTS (
        SELECT 1 FROM knowledge_chunks
        JOIN knowledge_document_versions ON knowledge_document_versions.id = knowledge_chunks.document_version_id
        JOIN knowledge_sources ON knowledge_sources.id = knowledge_document_versions.source_id
        WHERE knowledge_chunks.id = chunk_id AND knowledge_sources.owner_id = public.app_current_user_id()
    )
);

CREATE UNIQUE INDEX ix_textbook_block_annotations_active ON textbook_block_annotations ("chunk_id") WHERE superseded_by IS NULL;
CREATE INDEX ix_textbook_block_annotations_review ON textbook_block_annotations ("review_status");
```

## 4. 字段

| 字段 | 类型 | 约束/含义 |
| --- | --- | --- |
| id | UUID | PK；由 uuid5(chunk_id) 稳定生成 |
| chunk_id | UUID | FK knowledge_chunks，ON DELETE CASCADE |
| block_id | VARCHAR(80) | 教材块稳定 ID，如 TB-B1-0001-1-p0001-01 |
| kp_primary | TEXT | 主考点；non_content/vocab_gap 为空 |
| kp_secondary | JSONB | 兼考点数组，默认 `[]`；teacher 行清空 |
| module_id | VARCHAR(40) | 模块 ID，如 kp_01_set_logic；空白为非内容 |
| status | VARCHAR(16) | mapped / non_content / vocab_gap |
| classification_source | VARCHAR(16) | rule / model / teacher |
| confidence | NUMERIC(4,3) | 0–1；teacher 固定 1.0 |
| model_version | VARCHAR(120) | model 必填；teacher 为复核版本 |
| review_status | VARCHAR(16) | draft / needs_review / reviewed / rejected |
| rationale | TEXT | 模型理由或教师备注摘要 |
| superseded_by | UUID | 自 FK；NULL 表示 active |
| created_at/updated_at | TIMESTAMPTZ | 默认 now()；apply 更新 updated_at |

## 5. 写入映射

- 360 teacher：`classification_source=teacher`、`review_status=reviewed`；教师有 kp 时 `status=mapped`；教师为 `—` 时 `status=non_content`。
- 其余 1437 model：`classification_source=model`、`review_status=needs_review`；空 primary 且非 non_content 时 `status=vocab_gap`。
- `kp_secondary` 原样保留；`model_version=textbook-map-v3-2026-11-06`。
- upsert 以 `(chunk_id) WHERE superseded_by IS NULL` 为 active 唯一键；重复 apply 只更新有变化的行。

## 6. 应用结果

| 项 | 结果 |
| --- | --- |
| active 行数 | 1797 / 唯一 chunk 1797 |
| teacher / model | 360 / 1437 |
| status | mapped 1711、non_content 52、vocab_gap 34 |
| 索引 | pk、active 唯一 partial、review_status |
| RLS | enable + force；policy `pol_textbook_block_annotations_owner` |
| 抽样 join | 3 条 block_id 与 chunk 文本均命中 |
| check_all | 17/17 |

## 7. 回滚

```powershell
# 删除本表数据，保留表结构
.\.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --rollback
# 若 apply 前表不存在，可同时删表
.\.venv\Scripts\python.exe tools\kb_textbook_pg_draft.py --rollback --drop
```

备份文件：`var/textbook_mapping/backup_pg_draft_2026-11-06.json`（apply 前表不存在，记录空备份）。
