-- GENERATED FILE — do not edit by hand.
-- generator: database/generator/generate_ddl.py v0.1.0
-- registry_version: 0.1.0
-- registry_hash: ab2c7dac6bd9251a18ae4d26dde6adad68851c3fd0680463b8ee6d2ddee983e7
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

-- 质量规则身份；版本在 quality_rule_versions
CREATE TABLE quality_rules (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "category" VARCHAR(40) NOT NULL,
    "default_severity" VARCHAR(4) NOT NULL,
    "description" TEXT,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_rules PRIMARY KEY ("id"),
    CONSTRAINT uq_quality_rules_key UNIQUE ("key"),
    CONSTRAINT ck_quality_rules_severity CHECK (default_severity IN ('S0','S1','S2','S3')),
    CONSTRAINT ck_quality_rules_status CHECK (status IN ('active','deprecated'))
);

ALTER TABLE quality_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_rules_read ON quality_rules FOR SELECT USING (true);

-- 规则版本；不可变
CREATE TABLE quality_rule_versions (
    "id" UUID NOT NULL,
    "rule_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "severity" VARCHAR(4) NOT NULL,
    "is_blocking" BOOLEAN NOT NULL DEFAULT false,
    "definition" JSONB NOT NULL,
    "definition_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'draft',
    "effective_from" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_rule_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_rule_versions_rule_id FOREIGN KEY ("rule_id") REFERENCES quality_rules(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_rule_versions_rule_no UNIQUE ("rule_id", "version_no"),
    CONSTRAINT ck_quality_rule_versions_severity CHECK (severity IN ('S0','S1','S2','S3')),
    CONSTRAINT ck_quality_rule_versions_status CHECK (status IN ('draft','active','retired'))
);

ALTER TABLE quality_rule_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_rule_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_rule_versions_read ON quality_rule_versions FOR SELECT USING (true);

CREATE INDEX ix_quality_rule_versions_rule ON quality_rule_versions ("rule_id", "version_no");

-- 对固定内容快照执行质量规则
CREATE TABLE quality_check_runs (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "target_type" VARCHAR(24) NOT NULL,
    "target_id" UUID NOT NULL,
    "target_content_hash" CHAR(64) NOT NULL,
    "document_schema_version" VARCHAR(20) NOT NULL,
    "rule_policy_hash" CHAR(64) NOT NULL,
    "engine_version" VARCHAR(64) NOT NULL,
    "process_status" VARCHAR(24) NOT NULL DEFAULT 'queued',
    "gate_result" VARCHAR(24) NOT NULL DEFAULT 'not_evaluated',
    "issue_counts" JSONB,
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "error_code" VARCHAR(80),
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_check_runs PRIMARY KEY ("id"),
    CONSTRAINT ck_quality_check_runs_target_type CHECK (target_type IN ('draft_revision','material_version')),
    CONSTRAINT ck_quality_check_runs_process CHECK (process_status IN ('queued','running','succeeded','failed','cancelled','outcome_unknown')),
    CONSTRAINT ck_quality_check_runs_gate CHECK (gate_result IN ('not_evaluated','passed','passed_with_warnings','blocked','inconclusive'))
);

ALTER TABLE quality_check_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_check_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_check_runs_owner ON quality_check_runs FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_quality_check_runs_target ON quality_check_runs ("target_type", "target_id", "created_at");
CREATE INDEX ix_quality_check_runs_owner ON quality_check_runs ("owner_id", "process_status");

-- 本次 Run 固化的规则快照；保证事后可复现
CREATE TABLE quality_check_rule_snapshots (
    "id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "rule_id" UUID NOT NULL,
    "rule_version_id" UUID NOT NULL,
    "rule_key" VARCHAR(80) NOT NULL,
    "severity" VARCHAR(4) NOT NULL,
    "definition_hash" CHAR(64) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_check_rule_snapshots PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_check_rule_snapshots_run_id FOREIGN KEY ("run_id") REFERENCES quality_check_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_quality_check_rule_snapshots_rule_id FOREIGN KEY ("rule_id") REFERENCES quality_rules(id) ON DELETE RESTRICT,
    CONSTRAINT fk_quality_check_rule_snapshots_rule_version_id FOREIGN KEY ("rule_version_id") REFERENCES quality_rule_versions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_check_rule_snapshots_run_rule UNIQUE ("run_id", "rule_id")
);

ALTER TABLE quality_check_rule_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_check_rule_snapshots FORCE ROW LEVEL SECURITY;

-- 单条规则的检查结果
CREATE TABLE quality_check_results (
    "id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "rule_id" UUID NOT NULL,
    "rule_version_id" UUID NOT NULL,
    "node_id" UUID,
    "result" VARCHAR(24) NOT NULL,
    "message" TEXT,
    "detail" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_check_results PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_check_results_run_id FOREIGN KEY ("run_id") REFERENCES quality_check_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_quality_check_results_rule_id FOREIGN KEY ("rule_id") REFERENCES quality_rules(id) ON DELETE RESTRICT,
    CONSTRAINT fk_quality_check_results_rule_version_id FOREIGN KEY ("rule_version_id") REFERENCES quality_rule_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_quality_check_results_result CHECK (result IN ('passed','failed','warning','not_applicable','inconclusive'))
);

ALTER TABLE quality_check_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_check_results FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_check_results_run ON quality_check_results ("run_id", "result");
CREATE INDEX ix_quality_check_results_node ON quality_check_results ("node_id") WHERE node_id IS NOT NULL;

-- 需要教师处理的问题；由检查结果聚合而来
CREATE TABLE quality_issues (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "rule_id" UUID NOT NULL,
    "code" VARCHAR(80) NOT NULL,
    "severity" VARCHAR(4) NOT NULL,
    "title" VARCHAR(300) NOT NULL,
    "description" TEXT,
    "node_ids" TEXT[],
    "resolution_status" VARCHAR(24) NOT NULL DEFAULT 'unresolved',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_issues PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_issues_run_id FOREIGN KEY ("run_id") REFERENCES quality_check_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_quality_issues_rule_id FOREIGN KEY ("rule_id") REFERENCES quality_rules(id) ON DELETE RESTRICT,
    CONSTRAINT ck_quality_issues_severity CHECK (severity IN ('S0','S1','S2','S3')),
    CONSTRAINT ck_quality_issues_resolution CHECK (resolution_status IN ('unresolved','resolved','waived','invalidated','superseded'))
);

ALTER TABLE quality_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_issues FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_issues_owner ON quality_issues FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_quality_issues_run ON quality_issues ("run_id", "severity");
CREATE INDEX ix_quality_issues_owner_open ON quality_issues ("owner_id", "severity") WHERE resolution_status = 'unresolved';

-- 问题或结果的可追溯证据；必须是真实执行产物
CREATE TABLE quality_evidence (
    "id" UUID NOT NULL,
    "issue_id" UUID,
    "run_id" UUID NOT NULL,
    "evidence_type" VARCHAR(32) NOT NULL,
    "payload" JSONB NOT NULL,
    "payload_hash" CHAR(64) NOT NULL,
    "tool_name" VARCHAR(120),
    "tool_version" VARCHAR(64),
    "produced_at" TIMESTAMPTZ NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_evidence PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_evidence_issue_id FOREIGN KEY ("issue_id") REFERENCES quality_issues(id) ON DELETE CASCADE,
    CONSTRAINT fk_quality_evidence_run_id FOREIGN KEY ("run_id") REFERENCES quality_check_runs(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_evidence_type CHECK (evidence_type IN ('validator_output','rule_trace','test_run','locator_readback'))
);

ALTER TABLE quality_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_evidence FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_evidence_run ON quality_evidence ("run_id");
CREATE INDEX ix_quality_evidence_issue ON quality_evidence ("issue_id") WHERE issue_id IS NOT NULL;

-- 对固定内容快照执行数学验证
CREATE TABLE math_validation_runs (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "target_type" VARCHAR(24) NOT NULL,
    "target_id" UUID NOT NULL,
    "target_content_hash" CHAR(64) NOT NULL,
    "validator_version" VARCHAR(64) NOT NULL,
    "sympy_version" VARCHAR(32),
    "process_status" VARCHAR(24) NOT NULL DEFAULT 'queued',
    "validation_result" VARCHAR(24) NOT NULL DEFAULT 'not_evaluated',
    "coverage" JSONB,
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "error_code" VARCHAR(80),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_math_validation_runs PRIMARY KEY ("id"),
    CONSTRAINT ck_math_validation_runs_target_type CHECK (target_type IN ('draft_revision','material_version')),
    CONSTRAINT ck_math_validation_runs_process CHECK (process_status IN ('queued','running','succeeded','failed','cancelled','outcome_unknown')),
    CONSTRAINT ck_math_validation_runs_result CHECK (validation_result IN ('not_evaluated','validated','failed','inconclusive','unsupported'))
);

ALTER TABLE math_validation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE math_validation_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_math_validation_runs_owner ON math_validation_runs FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_math_validation_runs_target ON math_validation_runs ("target_type", "target_id", "created_at");

-- 按层记录数学验证证据
CREATE TABLE math_validation_evidence (
    "id" UUID NOT NULL,
    "run_id" UUID NOT NULL,
    "node_id" UUID,
    "layer" VARCHAR(24) NOT NULL,
    "claim" TEXT,
    "result" VARCHAR(24) NOT NULL,
    "method" VARCHAR(120),
    "payload" JSONB,
    "payload_hash" CHAR(64),
    "produced_at" TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_math_validation_evidence PRIMARY KEY ("id"),
    CONSTRAINT fk_math_validation_evidence_run_id FOREIGN KEY ("run_id") REFERENCES math_validation_runs(id) ON DELETE CASCADE,
    CONSTRAINT ck_math_validation_evidence_layer CHECK (layer IN ('formula','symbolic','numerical','solution','cross_material')),
    CONSTRAINT ck_math_validation_evidence_result CHECK (result IN ('validated','failed','inconclusive','unsupported'))
);

ALTER TABLE math_validation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE math_validation_evidence FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_math_validation_evidence_run ON math_validation_evidence ("run_id", "layer");

-- 教师对问题的反馈；用于规则改进
CREATE TABLE quality_issue_feedback (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "issue_id" UUID NOT NULL,
    "feedback_type" VARCHAR(24) NOT NULL,
    "reason" TEXT,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_issue_feedback PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_issue_feedback_issue_id FOREIGN KEY ("issue_id") REFERENCES quality_issues(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_issue_feedback_type CHECK (feedback_type IN ('agree','false_positive','unclear','other'))
);

ALTER TABLE quality_issue_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_issue_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_issue_feedback_owner ON quality_issue_feedback FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_quality_issue_feedback_issue ON quality_issue_feedback ("issue_id");

-- 问题处置记录；waive 必须留理由
CREATE TABLE quality_issue_resolutions (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "issue_id" UUID NOT NULL,
    "resolution" VARCHAR(24) NOT NULL,
    "reason" TEXT,
    "decided_by" UUID NOT NULL,
    "decided_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_issue_resolutions PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_issue_resolutions_issue_id FOREIGN KEY ("issue_id") REFERENCES quality_issues(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_issue_resolutions_value CHECK (resolution IN ('resolved','waived','invalidated','superseded')),
    CONSTRAINT ck_quality_issue_resolutions_reason CHECK (resolution <> 'waived' OR (reason IS NOT NULL AND length(trim(reason)) > 0))
);

ALTER TABLE quality_issue_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_issue_resolutions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_issue_resolutions_owner ON quality_issue_resolutions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_quality_issue_resolutions_issue ON quality_issue_resolutions ("issue_id");

-- 评估数据集身份
CREATE TABLE quality_datasets (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "domain" VARCHAR(40) NOT NULL DEFAULT 'mathematics',
    "description" TEXT,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_datasets PRIMARY KEY ("id"),
    CONSTRAINT uq_quality_datasets_key UNIQUE ("key"),
    CONSTRAINT ck_quality_datasets_status CHECK (status IN ('active','archived'))
);

ALTER TABLE quality_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_datasets FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_datasets_read ON quality_datasets FOR SELECT USING (true);

-- 数据集版本；不可变
CREATE TABLE quality_dataset_versions (
    "id" UUID NOT NULL,
    "dataset_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "item_count" INTEGER NOT NULL DEFAULT 0,
    "content_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'draft',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_dataset_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_dataset_versions_dataset_id FOREIGN KEY ("dataset_id") REFERENCES quality_datasets(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_dataset_versions_no UNIQUE ("dataset_id", "version_no"),
    CONSTRAINT ck_quality_dataset_versions_status CHECK (status IN ('draft','frozen','retired'))
);

ALTER TABLE quality_dataset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_dataset_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_dataset_versions_read ON quality_dataset_versions FOR SELECT USING (true);

-- 数据集样本；冻结后不可修改
CREATE TABLE quality_dataset_items (
    "id" UUID NOT NULL,
    "dataset_version_id" UUID NOT NULL,
    "item_key" VARCHAR(120) NOT NULL,
    "split" VARCHAR(16) NOT NULL DEFAULT 'test',
    "payload" JSONB NOT NULL,
    "expected" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_dataset_items PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_dataset_items_dataset_version_id FOREIGN KEY ("dataset_version_id") REFERENCES quality_dataset_versions(id) ON DELETE CASCADE,
    CONSTRAINT uq_quality_dataset_items_key UNIQUE ("dataset_version_id", "item_key"),
    CONSTRAINT ck_quality_dataset_items_split CHECK (split IN ('train','validation','test'))
);

ALTER TABLE quality_dataset_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_dataset_items FORCE ROW LEVEL SECURITY;

-- 评估定义；绑定数据集与目的
CREATE TABLE quality_evaluations (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "dataset_id" UUID NOT NULL,
    "purpose" VARCHAR(40) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_evaluations PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_evaluations_dataset_id FOREIGN KEY ("dataset_id") REFERENCES quality_datasets(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_evaluations_key UNIQUE ("key"),
    CONSTRAINT ck_quality_evaluations_status CHECK (status IN ('active','archived'))
);

ALTER TABLE quality_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_evaluations FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_evaluations_read ON quality_evaluations FOR SELECT USING (true);

-- 一次评估运行；固定数据集版本与全部影响结果的版本
CREATE TABLE quality_evaluation_runs (
    "id" UUID NOT NULL,
    "evaluation_id" UUID NOT NULL,
    "dataset_version_id" UUID NOT NULL,
    "model" VARCHAR(120) NOT NULL,
    "prompt_version" VARCHAR(64) NOT NULL,
    "harness_version" VARCHAR(64) NOT NULL,
    "plugin_manifest_hash" CHAR(64),
    "tool_registry_hash" CHAR(64),
    "validator_version" VARCHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'queued',
    "result_summary" JSONB,
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_evaluation_runs PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_evaluation_runs_evaluation_id FOREIGN KEY ("evaluation_id") REFERENCES quality_evaluations(id) ON DELETE RESTRICT,
    CONSTRAINT fk_quality_evaluation_runs_dataset_version_id FOREIGN KEY ("dataset_version_id") REFERENCES quality_dataset_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_quality_evaluation_runs_status CHECK (status IN ('queued','running','succeeded','failed','cancelled'))
);

ALTER TABLE quality_evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_evaluation_runs FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_evaluation_runs_evaluation ON quality_evaluation_runs ("evaluation_id", "created_at");

-- 单样本评估结果
CREATE TABLE quality_evaluation_results (
    "id" UUID NOT NULL,
    "evaluation_run_id" UUID NOT NULL,
    "dataset_item_id" UUID NOT NULL,
    "outcome" VARCHAR(24) NOT NULL,
    "score" NUMERIC(8,4),
    "detail" JSONB,
    CONSTRAINT pk_quality_evaluation_results PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_evaluation_results_evaluation_run_id FOREIGN KEY ("evaluation_run_id") REFERENCES quality_evaluation_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_quality_evaluation_results_dataset_item_id FOREIGN KEY ("dataset_item_id") REFERENCES quality_dataset_items(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_evaluation_results_item UNIQUE ("evaluation_run_id", "dataset_item_id"),
    CONSTRAINT ck_quality_evaluation_results_outcome CHECK (outcome IN ('passed','failed','inconclusive'))
);

ALTER TABLE quality_evaluation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_evaluation_results FORCE ROW LEVEL SECURITY;

-- 指标定义；含阻断标记
CREATE TABLE quality_metrics (
    "id" UUID NOT NULL,
    "key" VARCHAR(40) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "unit" VARCHAR(32),
    "direction" VARCHAR(16) NOT NULL,
    "target_numeric" NUMERIC(12,4),
    "is_blocking" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_metrics PRIMARY KEY ("id"),
    CONSTRAINT uq_quality_metrics_key UNIQUE ("key"),
    CONSTRAINT ck_quality_metrics_direction CHECK (direction IN ('higher_better','lower_better'))
);

ALTER TABLE quality_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_metrics FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_metrics_read ON quality_metrics FOR SELECT USING (true);

-- 指标观测值
CREATE TABLE quality_metric_observations (
    "id" UUID NOT NULL,
    "metric_id" UUID NOT NULL,
    "scope_type" VARCHAR(24) NOT NULL DEFAULT 'global',
    "scope_id" UUID,
    "value_numeric" NUMERIC(14,4) NOT NULL,
    "sample_size" INTEGER,
    "source" VARCHAR(80),
    "observed_at" TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_quality_metric_observations PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_metric_observations_metric_id FOREIGN KEY ("metric_id") REFERENCES quality_metrics(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_metric_observations_scope CHECK (scope_type IN ('global','tenant','material'))
);

ALTER TABLE quality_metric_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_metric_observations FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_metric_observations_metric ON quality_metric_observations ("metric_id", "observed_at");

-- 告警规则
CREATE TABLE quality_alerts (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "metric_id" UUID NOT NULL,
    "condition" JSONB NOT NULL,
    "severity" VARCHAR(16) NOT NULL DEFAULT 'warning',
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_alerts PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_alerts_metric_id FOREIGN KEY ("metric_id") REFERENCES quality_metrics(id) ON DELETE RESTRICT,
    CONSTRAINT uq_quality_alerts_key UNIQUE ("key"),
    CONSTRAINT ck_quality_alerts_severity CHECK (severity IN ('info','warning','critical')),
    CONSTRAINT ck_quality_alerts_status CHECK (status IN ('active','muted','resolved'))
);

ALTER TABLE quality_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_alerts FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_alerts_read ON quality_alerts FOR SELECT USING (true);

-- 告警事件流
CREATE TABLE quality_alert_events (
    "id" UUID NOT NULL,
    "alert_id" UUID NOT NULL,
    "event_type" VARCHAR(24) NOT NULL,
    "actor_id" UUID,
    "detail" JSONB,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_alert_events PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_alert_events_alert_id FOREIGN KEY ("alert_id") REFERENCES quality_alerts(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_alert_events_type CHECK (event_type IN ('triggered','acknowledged','resolved'))
);

ALTER TABLE quality_alert_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_alert_events FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_alert_events_alert ON quality_alert_events ("alert_id", "occurred_at");

-- 发布批次；固定模型、Prompt、Harness、插件、工具与 Validator 版本
CREATE TABLE quality_releases (
    "id" UUID NOT NULL,
    "version_label" VARCHAR(80) NOT NULL,
    "application_version" VARCHAR(64) NOT NULL,
    "model" VARCHAR(120) NOT NULL,
    "prompt_version" VARCHAR(64) NOT NULL,
    "harness_version" VARCHAR(64) NOT NULL,
    "plugin_manifest_hash" CHAR(64),
    "tool_registry_hash" CHAR(64),
    "validator_version" VARCHAR(64) NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'draft',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_releases PRIMARY KEY ("id"),
    CONSTRAINT uq_quality_releases_label UNIQUE ("version_label"),
    CONSTRAINT ck_quality_releases_status CHECK (status IN ('draft','canary','production','rolled_back'))
);

ALTER TABLE quality_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_releases FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_quality_releases_read ON quality_releases FOR SELECT USING (true);

-- 发布审批
CREATE TABLE quality_release_approvals (
    "id" UUID NOT NULL,
    "release_id" UUID NOT NULL,
    "approver_id" UUID NOT NULL,
    "decision" VARCHAR(16) NOT NULL,
    "reason" TEXT,
    "decided_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_release_approvals PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_release_approvals_release_id FOREIGN KEY ("release_id") REFERENCES quality_releases(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_release_approvals_decision CHECK (decision IN ('approved','rejected'))
);

ALTER TABLE quality_release_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_release_approvals FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_release_approvals_release ON quality_release_approvals ("release_id");

-- 发布过程事件；回滚不得删除教师已批准版本
CREATE TABLE quality_release_events (
    "id" UUID NOT NULL,
    "release_id" UUID NOT NULL,
    "event_type" VARCHAR(32) NOT NULL,
    "actor_id" UUID,
    "detail" JSONB,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_quality_release_events PRIMARY KEY ("id"),
    CONSTRAINT fk_quality_release_events_release_id FOREIGN KEY ("release_id") REFERENCES quality_releases(id) ON DELETE CASCADE,
    CONSTRAINT ck_quality_release_events_type CHECK (event_type IN ('canary_started','canary_passed','production_promoted','rolled_back'))
);

ALTER TABLE quality_release_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_release_events FORCE ROW LEVEL SECURITY;

CREATE INDEX ix_quality_release_events_release ON quality_release_events ("release_id", "occurred_at");

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
