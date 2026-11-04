-- GENERATED FILE — do not edit by hand.
-- generator: database/generator/generate_ddl.py v0.1.0
-- registry_version: 0.1.0
-- registry_hash: 2498a7b7307f650aa6ffed6bd4798cb1a6919c8a0d904f94fa4c741054e6e64b
-- variant: core (optional tables excluded)
-- regenerate with: python database/generator/generate_ddl.py

-- skipped optional tables: knowledge_question_embeddings
-- include them with: python database/generator/generate_ddl.py --with-optional
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- optional: 仅当需要数据库侧随机函数时启用；UUIDv7 由应用生成
-- CREATE EXTENSION IF NOT EXISTS pgvector;  -- optional: 可选；仅 knowledge_question_embeddings 使用

-- Session context functions (master §10.3)
-- 事务级 GUC 中的当前用户；未设置时返回 NULL
CREATE OR REPLACE FUNCTION public.app_current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.current_user_id', true), '')::uuid
$$;
-- 事务级 GUC 中的请求 ID
CREATE OR REPLACE FUNCTION public.app_current_request_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.current_request_id', true), '')::uuid
$$;
-- 事务级 GUC 中的执行 ID
CREATE OR REPLACE FUNCTION public.app_current_execution_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('app.current_execution_id', true), '')::uuid
$$;

-- 教学专题；一个 Project 对应一个教学专题
CREATE TABLE projects (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "name" VARCHAR(160) NOT NULL,
    "description" TEXT,
    "subject" VARCHAR(32) NOT NULL DEFAULT 'mathematics',
    "grade" VARCHAR(32) NOT NULL DEFAULT 'senior_high',
    "cover_storage_key" VARCHAR(500),
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "archived_at" TIMESTAMPTZ,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_projects PRIMARY KEY ("id"),
    CONSTRAINT ck_projects_status CHECK (status IN ('active','archived'))
);

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_projects_owner ON projects FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_projects_owner ON projects ("owner_id", "status", "updated_at") WHERE deleted_at IS NULL;

-- 教学材料身份；primary_project_id 为空表示个人材料库
CREATE TABLE materials (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "primary_project_id" UUID,
    "title" VARCHAR(500) NOT NULL,
    "document_kind" VARCHAR(32) NOT NULL DEFAULT 'mixed',
    "current_version_id" UUID,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_materials PRIMARY KEY ("id"),
    CONSTRAINT fk_materials_primary_project_id FOREIGN KEY ("primary_project_id") REFERENCES projects(id) ON DELETE RESTRICT,
    CONSTRAINT ck_materials_document_kind CHECK (document_kind IN ('lesson','exercise_set','worksheet','mixed'))
);

ALTER TABLE materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE materials FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_materials_owner ON materials FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_materials_owner ON materials ("owner_id", "updated_at") WHERE deleted_at IS NULL;
CREATE INDEX ix_materials_project ON materials ("primary_project_id") WHERE deleted_at IS NULL;

-- 不可变正式版本；修改必须创建新版本
CREATE TABLE material_versions (
    "id" UUID NOT NULL,
    "material_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "document_schema_version" VARCHAR(20) NOT NULL,
    "document_content" JSONB NOT NULL,
    "content_hash" CHAR(64) NOT NULL,
    "change_summary" TEXT,
    "source_draft_revision_id" UUID,
    "publication_approval_id" UUID,
    "idempotency_key" VARCHAR(255) NOT NULL,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_material_versions_material_id FOREIGN KEY ("material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_versions_material_version UNIQUE ("material_id", "version_no"),
    CONSTRAINT uq_material_versions_idempotency UNIQUE ("owner_id", "idempotency_key")
);

ALTER TABLE material_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_versions_owner ON material_versions FOR SELECT USING (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_versions_material ON material_versions ("material_id", "version_no");

-- 可编辑草稿；基版本、当前 Revision 指针与状态机
CREATE TABLE material_drafts (
    "id" UUID NOT NULL,
    "material_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "base_version_id" UUID,
    "current_revision_id" UUID,
    "current_revision_no" INTEGER NOT NULL DEFAULT 0,
    "current_content_hash" CHAR(64),
    "status" VARCHAR(32) NOT NULL DEFAULT 'editing',
    "state_version" INTEGER NOT NULL DEFAULT 0,
    "state_changed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "status_reason_code" VARCHAR(80),
    "status_reason" TEXT,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_drafts PRIMARY KEY ("id"),
    CONSTRAINT fk_material_drafts_material_id FOREIGN KEY ("material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_drafts_base_version_id FOREIGN KEY ("base_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_material_drafts_status CHECK (status IN ('editing','checking','changes_required','awaiting_review','approved','needs_rebase','needs_attention','published','abandoned','superseded')),
    CONSTRAINT ck_material_drafts_state_version CHECK (state_version >= 0 AND current_revision_no >= 0)
);

ALTER TABLE material_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_drafts FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_drafts_owner ON material_drafts FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_drafts_material ON material_drafts ("material_id", "status");
CREATE INDEX ix_material_drafts_owner_status ON material_drafts ("owner_id", "status");

-- 不可变草稿修订快照；被检查或审批引用后永久保留
CREATE TABLE material_draft_revisions (
    "id" UUID NOT NULL,
    "draft_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "revision_no" INTEGER NOT NULL,
    "parent_revision_id" UUID,
    "document_schema_version" VARCHAR(20) NOT NULL,
    "content" JSONB NOT NULL,
    "content_hash" CHAR(64) NOT NULL,
    "change_origin" VARCHAR(32) NOT NULL,
    "revision_class" VARCHAR(16) NOT NULL DEFAULT 'checkpoint',
    "change_summary" TEXT,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_draft_revisions PRIMARY KEY ("id"),
    CONSTRAINT fk_material_draft_revisions_draft_id FOREIGN KEY ("draft_id") REFERENCES material_drafts(id) ON DELETE CASCADE,
    CONSTRAINT fk_material_draft_revisions_parent_revision_id FOREIGN KEY ("parent_revision_id") REFERENCES material_draft_revisions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_draft_revisions_draft_no UNIQUE ("draft_id", "revision_no"),
    CONSTRAINT ck_material_draft_revisions_origin CHECK (change_origin IN ('teacher_edit','chat_revision','agent_generation','rebase','restore','import')),
    CONSTRAINT ck_material_draft_revisions_class CHECK (revision_class IN ('checkpoint','autosave'))
);

ALTER TABLE material_draft_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_draft_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_draft_revisions_owner ON material_draft_revisions FOR SELECT USING (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_draft_revisions_draft ON material_draft_revisions ("draft_id", "revision_no");

-- Teaching Document Schema Registry；K014 引用来执行检查
CREATE TABLE document_schema_definitions (
    "id" UUID NOT NULL,
    "schema_id" VARCHAR(120) NOT NULL,
    "schema_version" VARCHAR(20) NOT NULL,
    "json_schema" JSONB NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_document_schema_definitions PRIMARY KEY ("id"),
    CONSTRAINT uq_document_schema_definitions_id_version UNIQUE ("schema_id", "schema_version"),
    CONSTRAINT ck_document_schema_definitions_status CHECK (status IN ('active','deprecated'))
);

ALTER TABLE document_schema_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_schema_definitions FORCE ROW LEVEL SECURITY;

-- 材料间引用；latest 跟随、pinned 固定版本
CREATE TABLE material_references (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "source_material_id" UUID NOT NULL,
    "target_material_id" UUID NOT NULL,
    "target_version_id" UUID,
    "mode" VARCHAR(16) NOT NULL DEFAULT 'latest',
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_references PRIMARY KEY ("id"),
    CONSTRAINT fk_material_references_source_material_id FOREIGN KEY ("source_material_id") REFERENCES materials(id) ON DELETE CASCADE,
    CONSTRAINT fk_material_references_target_material_id FOREIGN KEY ("target_material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_references_target_version_id FOREIGN KEY ("target_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_material_references_mode CHECK ((mode = 'latest' AND target_version_id IS NULL) OR (mode = 'pinned' AND target_version_id IS NOT NULL))
);

ALTER TABLE material_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_references FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_references_owner ON material_references FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_references_source ON material_references ("source_material_id");
CREATE INDEX ix_material_references_target ON material_references ("target_material_id");

-- 任务与具体 Material Version 的交付关系
CREATE TABLE task_material_links (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "material_id" UUID NOT NULL,
    "material_version_id" UUID NOT NULL,
    "relation" VARCHAR(32) NOT NULL DEFAULT 'deliverable',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_task_material_links PRIMARY KEY ("id"),
    CONSTRAINT fk_task_material_links_material_id FOREIGN KEY ("material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT fk_task_material_links_material_version_id FOREIGN KEY ("material_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_task_material_links_task_version UNIQUE ("task_id", "material_version_id"),
    CONSTRAINT ck_task_material_links_relation CHECK (relation IN ('deliverable','reference'))
);

-- DEFERRED FK: task_material_links."task_id" -> tasks(id) (target owned by another module, add it once that module exists)

ALTER TABLE task_material_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_material_links FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_task_material_links_owner ON task_material_links FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_task_material_links_version ON task_material_links ("material_version_id");

-- 单次消费的发布授权；固定 Revision、Gate 快照与权利快照
CREATE TABLE material_publication_approvals (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "material_id" UUID NOT NULL,
    "draft_id" UUID NOT NULL,
    "draft_revision_id" UUID NOT NULL,
    "draft_content_hash" CHAR(64) NOT NULL,
    "base_version_id" UUID,
    "document_schema_version" VARCHAR(20) NOT NULL,
    "required_quality_run_ids" TEXT[],
    "required_math_run_ids" TEXT[],
    "quality_policy_hash" CHAR(64) NOT NULL,
    "gate_snapshot_hash" CHAR(64) NOT NULL,
    "citation_snapshot_hash" CHAR(64) NOT NULL,
    "profile_config_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'pending',
    "approver_id" UUID,
    "approved_at" TIMESTAMPTZ,
    "expires_at" TIMESTAMPTZ,
    "consumed_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_publication_approvals PRIMARY KEY ("id"),
    CONSTRAINT fk_material_publication_approvals_material_id FOREIGN KEY ("material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_publication_approvals_draft_id FOREIGN KEY ("draft_id") REFERENCES material_drafts(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_publication_approvals_draft_revision_id FOREIGN KEY ("draft_revision_id") REFERENCES material_draft_revisions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_publication_approvals_base_version_id FOREIGN KEY ("base_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_material_publication_approvals_status CHECK (status IN ('pending','approved','rejected','invalidated','expired','consumed')),
    CONSTRAINT ck_material_publication_approvals_consumed CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);

ALTER TABLE material_publication_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_publication_approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_publication_approvals_owner ON material_publication_approvals FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_publication_approvals_draft ON material_publication_approvals ("draft_id", "status");
CREATE INDEX ix_material_publication_approvals_owner ON material_publication_approvals ("owner_id", "status");

-- 导出记录；固定版本、Profile、Renderer 与选项 Hash
CREATE TABLE material_exports (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "material_version_id" UUID NOT NULL,
    "profile" VARCHAR(16) NOT NULL,
    "format" VARCHAR(16) NOT NULL,
    "renderer_version" VARCHAR(64) NOT NULL,
    "options_hash" CHAR(64) NOT NULL,
    "source_document_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'queued',
    "storage_key" VARCHAR(500),
    "file_hash" CHAR(64),
    "file_size_bytes" BIGINT,
    "idempotency_key" VARCHAR(255) NOT NULL,
    "error_code" VARCHAR(80),
    "expires_at" TIMESTAMPTZ,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "finished_at" TIMESTAMPTZ,
    CONSTRAINT pk_material_exports PRIMARY KEY ("id"),
    CONSTRAINT fk_material_exports_material_version_id FOREIGN KEY ("material_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_exports_idempotency UNIQUE ("owner_id", "idempotency_key"),
    CONSTRAINT ck_material_exports_profile CHECK (profile IN ('teacher','student')),
    CONSTRAINT ck_material_exports_format CHECK (format IN ('docx','pdf')),
    CONSTRAINT ck_material_exports_status CHECK (status IN ('queued','rendering','uploading','ready','failed','cancelled','outcome_unknown','expired')),
    CONSTRAINT ck_material_exports_ready_storage CHECK (status <> 'ready' OR storage_key IS NOT NULL)
);

ALTER TABLE material_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_exports FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_exports_owner ON material_exports FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_exports_version ON material_exports ("material_version_id", "created_at");
CREATE INDEX ix_material_exports_owner ON material_exports ("owner_id", "status");

-- 分类树；平台提供四个默认分类，教师可新建私有分类
CREATE TABLE knowledge_categories (
    "id" UUID NOT NULL,
    "scope" VARCHAR(16) NOT NULL,
    "owner_id" UUID,
    "parent_id" UUID,
    "key" VARCHAR(64) NOT NULL,
    "name" VARCHAR(120) NOT NULL,
    "source_type" VARCHAR(32),
    "sort_order" SMALLINT NOT NULL DEFAULT 0,
    "is_system" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_categories PRIMARY KEY ("id"),
    CONSTRAINT uq_knowledge_categories_scope_owner_key UNIQUE ("scope", "owner_id", "key"),
    CONSTRAINT ck_knowledge_categories_scope_owner CHECK ((scope = 'platform' AND owner_id IS NULL) OR (scope = 'teacher' AND owner_id IS NOT NULL)),
    CONSTRAINT ck_knowledge_categories_source_type CHECK (source_type IS NULL OR source_type IN ('textbook','workbook','gaokao_paper','mock_exam','other'))
);

ALTER TABLE knowledge_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_categories FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_knowledge_categories_select ON knowledge_categories FOR SELECT USING (scope = 'platform' OR owner_id = public.app_current_user_id());

CREATE INDEX ix_knowledge_categories_owner ON knowledge_categories ("scope", "owner_id", "sort_order");
CREATE INDEX ix_knowledge_categories_parent ON knowledge_categories ("parent_id");

-- 来源身份与归属；一本书或一套卷子一条
CREATE TABLE knowledge_sources (
    "id" UUID NOT NULL,
    "scope" VARCHAR(16) NOT NULL,
    "owner_id" UUID,
    "category_id" UUID NOT NULL,
    "source_type" VARCHAR(32) NOT NULL,
    "title" VARCHAR(500) NOT NULL,
    "publisher" VARCHAR(300),
    "edition" VARCHAR(200),
    "year" SMALLINT,
    "region" VARCHAR(100),
    "paper_name" VARCHAR(200),
    "language" VARCHAR(20) NOT NULL DEFAULT 'zh-CN',
    "rights_status" VARCHAR(32) NOT NULL,
    "distribution_scope" VARCHAR(32) NOT NULL DEFAULT 'private_teacher',
    "derived_from_source_id" UUID,
    "metadata" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_knowledge_sources PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_sources_category_id FOREIGN KEY ("category_id") REFERENCES knowledge_categories(id) ON DELETE RESTRICT,
    CONSTRAINT fk_knowledge_sources_derived_from_source_id FOREIGN KEY ("derived_from_source_id") REFERENCES knowledge_sources(id) ON DELETE RESTRICT,
    CONSTRAINT ck_knowledge_sources_scope_owner CHECK ((scope = 'platform' AND owner_id IS NULL) OR (scope = 'teacher' AND owner_id IS NOT NULL)),
    CONSTRAINT ck_knowledge_sources_platform_rights CHECK (scope <> 'platform' OR (rights_status = 'licensed' AND distribution_scope = 'classroom')),
    CONSTRAINT ck_knowledge_sources_rights_status CHECK (rights_status IN ('unverified','teacher_confirmed','licensed','restricted')),
    CONSTRAINT ck_knowledge_sources_distribution_scope CHECK (distribution_scope IN ('private_teacher','classroom','public')),
    CONSTRAINT ck_knowledge_sources_source_type CHECK (source_type IN ('textbook','workbook','gaokao_paper','mock_exam','other'))
);

ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_knowledge_sources_select ON knowledge_sources FOR SELECT USING (scope = 'platform' OR owner_id = public.app_current_user_id());
CREATE POLICY pol_knowledge_sources_write ON knowledge_sources FOR ALL USING (scope = 'teacher' AND owner_id = public.app_current_user_id()) WITH CHECK (scope = 'teacher' AND owner_id = public.app_current_user_id());

CREATE INDEX ix_knowledge_sources_category ON knowledge_sources ("scope", "category_id", "source_type") WHERE deleted_at IS NULL;
CREATE INDEX ix_knowledge_sources_owner ON knowledge_sources ("owner_id", "source_type") WHERE deleted_at IS NULL;

-- 文件版本；解析、审核、索引挂在版本上
CREATE TABLE knowledge_document_versions (
    "id" UUID NOT NULL,
    "source_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "storage_key" VARCHAR(500) NOT NULL,
    "checksum_sha256" CHAR(64) NOT NULL,
    "mime_type" VARCHAR(120) NOT NULL,
    "file_size_bytes" BIGINT NOT NULL,
    "page_count" INTEGER,
    "parser_version" VARCHAR(64),
    "parse_schema_version" VARCHAR(20),
    "lifecycle_status" VARCHAR(32) NOT NULL DEFAULT 'processing',
    "submitted_at" TIMESTAMPTZ,
    "approved_at" TIMESTAMPTZ,
    "indexed_at" TIMESTAMPTZ,
    "withdrawn_at" TIMESTAMPTZ,
    "uploaded_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_document_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_document_versions_source_id FOREIGN KEY ("source_id") REFERENCES knowledge_sources(id) ON DELETE RESTRICT,
    CONSTRAINT uq_knowledge_document_versions_source_version UNIQUE ("source_id", "version_no"),
    CONSTRAINT ck_knowledge_document_versions_status CHECK (lifecycle_status IN ('processing','pending_review','approved','indexed','failed','quarantined','rejected','withdrawn','deleted'))
);

ALTER TABLE knowledge_document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_document_versions FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_document_versions_source ON knowledge_document_versions ("source_id", "version_no");
CREATE INDEX ix_knowledge_document_versions_status ON knowledge_document_versions ("lifecycle_status");

-- 文本块；Citation 的定位单元
CREATE TABLE knowledge_chunks (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "chunk_key" VARCHAR(200) NOT NULL,
    "ordinal" INTEGER NOT NULL,
    "text_content" TEXT NOT NULL,
    "text_hash" CHAR(64) NOT NULL,
    "locator" JSONB NOT NULL,
    "content_kind" VARCHAR(16) NOT NULL DEFAULT 'text',
    "parser_version" VARCHAR(64) NOT NULL,
    "parse_schema_version" VARCHAR(20) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_chunks PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_chunks_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT uq_knowledge_chunks_parse_identity UNIQUE ("document_version_id", "parser_version", "parse_schema_version", "chunk_key"),
    CONSTRAINT ck_knowledge_chunks_content_kind CHECK (content_kind IN ('text','formula','table','figure'))
);

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_chunks_version_order ON knowledge_chunks ("document_version_id", "ordinal");

-- 题目单元；检索与引用的最小单位
CREATE TABLE knowledge_questions (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "question_no" VARCHAR(32) NOT NULL,
    "section_label" VARCHAR(120),
    "ordinal" INTEGER NOT NULL,
    "stem_locator" JSONB NOT NULL,
    "answer_locator" JSONB,
    "score" NUMERIC(5,2),
    "segmentation_status" VARCHAR(16) NOT NULL DEFAULT 'auto',
    "segmentation_source" VARCHAR(16) NOT NULL DEFAULT 'rule',
    "current_paper_question_type" VARCHAR(32) NOT NULL,
    "current_knowledge_points" TEXT[],
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_questions PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_questions_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT uq_knowledge_questions_version_no UNIQUE ("document_version_id", "question_no"),
    CONSTRAINT ck_knowledge_questions_paper_type CHECK (current_paper_question_type IN ('single_choice','multiple_choice','fill_blank','free_response')),
    CONSTRAINT ck_knowledge_questions_score CHECK (score IS NULL OR score >= 0),
    CONSTRAINT ck_knowledge_questions_segmentation CHECK (segmentation_status IN ('auto','accepted','corrected','rejected') AND segmentation_source IN ('rule','model','teacher'))
);

ALTER TABLE knowledge_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_questions FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_questions_version_order ON knowledge_questions ("document_version_id", "ordinal");
CREATE INDEX ix_knowledge_questions_paper_type ON knowledge_questions ("current_paper_question_type");
CREATE INDEX ix_knowledge_questions_segmentation ON knowledge_questions ("segmentation_status") WHERE segmentation_status <> 'accepted';

-- 派生标注；带版本，不覆盖历史
CREATE TABLE knowledge_annotations (
    "id" UUID NOT NULL,
    "question_id" UUID NOT NULL,
    "annotation_type" VARCHAR(32) NOT NULL,
    "value" TEXT NOT NULL,
    "classification_source" VARCHAR(16) NOT NULL,
    "confidence" NUMERIC(4,3),
    "model_version" VARCHAR(120),
    "superseded_by" UUID,
    "created_by" UUID,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_annotations PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_annotations_question_id FOREIGN KEY ("question_id") REFERENCES knowledge_questions(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_annotations_superseded_by FOREIGN KEY ("superseded_by") REFERENCES knowledge_annotations(id) ON DELETE RESTRICT,
    CONSTRAINT ck_knowledge_annotations_source CHECK (classification_source IN ('rule','model','teacher')),
    CONSTRAINT ck_knowledge_annotations_model_version CHECK (classification_source <> 'model' OR model_version IS NOT NULL)
);

ALTER TABLE knowledge_annotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_annotations FORCE ROW LEVEL SECURITY;

CREATE UNIQUE INDEX ix_knowledge_annotations_active ON knowledge_annotations ("question_id", "annotation_type") WHERE superseded_by IS NULL;

-- 处理记录；扫描、解析、切分、分类、索引各阶段
CREATE TABLE knowledge_ingestion_runs (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "stage" VARCHAR(16) NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "tool_version" VARCHAR(120),
    "started_at" TIMESTAMPTZ NOT NULL,
    "finished_at" TIMESTAMPTZ,
    "error_code" VARCHAR(80),
    "error_detail" TEXT,
    "metrics" JSONB,
    CONSTRAINT pk_knowledge_ingestion_runs PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_ingestion_runs_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_ingestion_runs_stage CHECK (stage IN ('scan','parse','ocr','segment','classify','index')),
    CONSTRAINT ck_knowledge_ingestion_runs_status CHECK (status IN ('running','succeeded','failed','cancelled'))
);

ALTER TABLE knowledge_ingestion_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_ingestion_runs FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_ingestion_runs_version ON knowledge_ingestion_runs ("document_version_id", "stage", "started_at");

-- 审核记录；来源审核、切分校对、标注修正、权利确认
CREATE TABLE knowledge_reviews (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "review_type" VARCHAR(32) NOT NULL,
    "target_id" UUID,
    "decision" VARCHAR(16) NOT NULL,
    "target_hash" CHAR(64),
    "reviewer_id" UUID NOT NULL,
    "notes" TEXT,
    "reviewed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_reviews PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_reviews_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_reviews_type CHECK (review_type IN ('source_approval','segmentation','annotation','rights')),
    CONSTRAINT ck_knowledge_reviews_decision CHECK (decision IN ('approved','rejected','needs_changes'))
);

ALTER TABLE knowledge_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_reviews FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_reviews_version ON knowledge_reviews ("document_version_id", "review_type");
CREATE INDEX ix_knowledge_reviews_target ON knowledge_reviews ("target_id");

-- 索引任务队列
CREATE TABLE knowledge_indexing_jobs (
    "id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "job_type" VARCHAR(32) NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "scheduled_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "attempt" SMALLINT NOT NULL DEFAULT 0,
    "error_code" VARCHAR(80),
    CONSTRAINT pk_knowledge_indexing_jobs PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_indexing_jobs_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT ck_knowledge_indexing_jobs_status CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    CONSTRAINT ck_knowledge_indexing_jobs_type CHECK (job_type IN ('keyword','embedding','full_rebuild'))
);

ALTER TABLE knowledge_indexing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_indexing_jobs FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_indexing_jobs_queue ON knowledge_indexing_jobs ("status", "scheduled_at") WHERE status IN ('queued','running');

-- 检索运行；Citation 的检索证据
CREATE TABLE knowledge_retrieval_runs (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "query_text" TEXT,
    "query_hash" CHAR(64) NOT NULL,
    "filters" JSONB,
    "top_k" SMALLINT NOT NULL DEFAULT 20,
    "result_count" INTEGER,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_knowledge_retrieval_runs PRIMARY KEY ("id")
);

ALTER TABLE knowledge_retrieval_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_retrieval_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_knowledge_retrieval_runs_owner ON knowledge_retrieval_runs FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_knowledge_retrieval_runs_owner ON knowledge_retrieval_runs ("owner_id", "created_at");

-- 检索结果；证明引用确实来自一次检索
CREATE TABLE knowledge_retrieval_results (
    "id" UUID NOT NULL,
    "retrieval_run_id" UUID NOT NULL,
    "question_id" UUID NOT NULL,
    "rank" SMALLINT NOT NULL,
    "score" NUMERIC(8,4),
    "matched_chunk_id" UUID,
    CONSTRAINT pk_knowledge_retrieval_results PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_retrieval_results_retrieval_run_id FOREIGN KEY ("retrieval_run_id") REFERENCES knowledge_retrieval_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_retrieval_results_question_id FOREIGN KEY ("question_id") REFERENCES knowledge_questions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_knowledge_retrieval_results_matched_chunk_id FOREIGN KEY ("matched_chunk_id") REFERENCES knowledge_chunks(id) ON DELETE RESTRICT,
    CONSTRAINT uq_knowledge_retrieval_results_run_question UNIQUE ("retrieval_run_id", "question_id")
);

ALTER TABLE knowledge_retrieval_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_retrieval_results FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_knowledge_retrieval_results_run ON knowledge_retrieval_results ("retrieval_run_id", "rank");

-- 引用投影；发布时从不可变 AST 固化
CREATE TABLE material_knowledge_citations (
    "id" UUID NOT NULL,
    "material_version_id" UUID NOT NULL,
    "content_node_id" UUID NOT NULL,
    "citation_id" UUID NOT NULL,
    "source_id" UUID NOT NULL,
    "document_version_id" UUID NOT NULL,
    "question_id" UUID,
    "chunk_id" UUID NOT NULL,
    "excerpt_hash" CHAR(64) NOT NULL,
    "rights_status_snapshot" VARCHAR(32) NOT NULL,
    "distribution_scope_snapshot" VARCHAR(32) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_material_knowledge_citations PRIMARY KEY ("id"),
    CONSTRAINT fk_material_knowledge_citations_source_id FOREIGN KEY ("source_id") REFERENCES knowledge_sources(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_knowledge_citations_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_knowledge_citations_question_id FOREIGN KEY ("question_id") REFERENCES knowledge_questions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_knowledge_citations_chunk_id FOREIGN KEY ("chunk_id") REFERENCES knowledge_chunks(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_knowledge_citations_version_citation UNIQUE ("material_version_id", "citation_id")
);

ALTER TABLE material_knowledge_citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_knowledge_citations FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_material_knowledge_citations_version ON material_knowledge_citations ("material_version_id");
CREATE INDEX ix_material_knowledge_citations_source ON material_knowledge_citations ("source_id");
CREATE INDEX ix_material_knowledge_citations_question ON material_knowledge_citations ("question_id") WHERE question_id IS NOT NULL;

-- Deferred foreign keys (circular or forward references)
ALTER TABLE materials ADD CONSTRAINT fk_materials_current_version_id FOREIGN KEY ("current_version_id") REFERENCES material_versions(id) ON DELETE SET NULL;
ALTER TABLE material_versions ADD CONSTRAINT fk_material_versions_source_draft_revision_id FOREIGN KEY ("source_draft_revision_id") REFERENCES material_draft_revisions(id) ON DELETE SET NULL;
ALTER TABLE material_versions ADD CONSTRAINT fk_material_versions_publication_approval_id FOREIGN KEY ("publication_approval_id") REFERENCES material_publication_approvals(id) ON DELETE RESTRICT;
ALTER TABLE material_drafts ADD CONSTRAINT fk_material_drafts_current_revision_id FOREIGN KEY ("current_revision_id") REFERENCES material_draft_revisions(id) ON DELETE SET NULL;

-- Grants are intentionally not generated: they depend on deployment roles.
-- Runtime role must not own tables or have BYPASSRLS (see §10.2).
