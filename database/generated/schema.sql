-- GENERATED FILE — do not edit by hand.
-- generator: database/generator/generate_ddl.py v0.1.0
-- registry_version: 0.1.0
-- registry_hash: 9c60efb85e26e796900460a7488b3113cec9a418ac726c7d0a62b559fb6e7128
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

-- 稳定身份主体；username 可变，id 不变
CREATE TABLE users (
    "id" UUID NOT NULL,
    "username" VARCHAR(64) NOT NULL,
    "display_name" VARCHAR(120),
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "is_admin" BOOLEAN NOT NULL DEFAULT false,
    "locale" VARCHAR(16) NOT NULL DEFAULT 'zh-CN',
    "timezone" VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    "closed_at" TIMESTAMPTZ,
    "last_login_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_users PRIMARY KEY ("id"),
    CONSTRAINT uq_users_username UNIQUE ("username"),
    CONSTRAINT ck_users_status CHECK (status IN ('active','suspended','closed')),
    CONSTRAINT ck_users_closed_at CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
    CONSTRAINT ck_users_username_lower CHECK (username = lower(username))
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_users_service ON users FOR ALL USING (true) WITH CHECK (true);

-- 登录凭据；与身份主体分离，只存不可逆 Hash
CREATE TABLE user_credentials (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "password_hash" VARCHAR(255) NOT NULL,
    "algorithm" VARCHAR(32) NOT NULL DEFAULT 'argon2id',
    "password_changed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "must_change_password" BOOLEAN NOT NULL DEFAULT false,
    "failed_attempts" SMALLINT NOT NULL DEFAULT 0,
    "locked_until" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_credentials PRIMARY KEY ("id"),
    CONSTRAINT fk_user_credentials_user_id FOREIGN KEY ("user_id") REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_credentials_user UNIQUE ("user_id"),
    CONSTRAINT ck_user_credentials_attempts CHECK (failed_attempts >= 0)
);

ALTER TABLE user_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_user_credentials_service ON user_credentials FOR ALL USING (true) WITH CHECK (true);

-- 用户名历史；改名后保留旧名，防冒用
CREATE TABLE user_username_history (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "username" VARCHAR(64) NOT NULL,
    "changed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "reason" VARCHAR(200),
    CONSTRAINT pk_user_username_history PRIMARY KEY ("id"),
    CONSTRAINT fk_user_username_history_user_id FOREIGN KEY ("user_id") REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_username_history_name UNIQUE ("username")
);

ALTER TABLE user_username_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_username_history FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_user_username_history_owner ON user_username_history FOR ALL USING (user_id = public.app_current_user_id()) WITH CHECK (user_id = public.app_current_user_id());

CREATE INDEX ix_user_username_history_user ON user_username_history ("user_id");

-- 邮箱；多个，验证前不能用于身份确认或通知
CREATE TABLE user_email_addresses (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "email" VARCHAR(320) NOT NULL,
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "verified_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_email_addresses PRIMARY KEY ("id"),
    CONSTRAINT fk_user_email_addresses_user_id FOREIGN KEY ("user_id") REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_email_addresses_email UNIQUE ("email"),
    CONSTRAINT ck_user_email_addresses_lower CHECK (email = lower(email))
);

ALTER TABLE user_email_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_email_addresses FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_user_email_addresses_owner ON user_email_addresses FOR ALL USING (user_id = public.app_current_user_id()) WITH CHECK (user_id = public.app_current_user_id());

CREATE INDEX ix_user_email_addresses_user ON user_email_addresses ("user_id");

-- 登录会话；只存 Token Hash
CREATE TABLE user_sessions (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "token_hash" CHAR(64) NOT NULL,
    "issued_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "expires_at" TIMESTAMPTZ NOT NULL,
    "revoked_at" TIMESTAMPTZ,
    "last_seen_at" TIMESTAMPTZ,
    "user_agent" VARCHAR(500),
    "ip_address" VARCHAR(45),
    CONSTRAINT pk_user_sessions PRIMARY KEY ("id"),
    CONSTRAINT fk_user_sessions_user_id FOREIGN KEY ("user_id") REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_sessions_token UNIQUE ("token_hash")
);

ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_user_sessions_service ON user_sessions FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_user_sessions_user ON user_sessions ("user_id", "expires_at");

-- 一次性令牌；邮箱验证与密码重置共用，靠 purpose 区分
CREATE TABLE user_verification_tokens (
    "id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "purpose" VARCHAR(32) NOT NULL,
    "token_hash" CHAR(64) NOT NULL,
    "target_email" VARCHAR(320),
    "requested_ip" VARCHAR(45),
    "expires_at" TIMESTAMPTZ NOT NULL,
    "consumed_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_user_verification_tokens PRIMARY KEY ("id"),
    CONSTRAINT fk_user_verification_tokens_user_id FOREIGN KEY ("user_id") REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_user_verification_tokens_hash UNIQUE ("token_hash"),
    CONSTRAINT ck_user_verification_tokens_purpose CHECK (purpose IN ('email_verify','password_reset'))
);

ALTER TABLE user_verification_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_verification_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_user_verification_tokens_owner ON user_verification_tokens FOR ALL USING (user_id = public.app_current_user_id()) WITH CHECK (user_id = public.app_current_user_id());

CREATE INDEX ix_user_verification_tokens_user ON user_verification_tokens ("user_id", "purpose");

-- 通用管理员审计；与 K021 的 security events 分离
CREATE TABLE admin_audit_logs (
    "id" UUID NOT NULL,
    "actor_id" UUID,
    "action" VARCHAR(120) NOT NULL,
    "target_type" VARCHAR(64),
    "target_id" UUID,
    "detail" JSONB,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_admin_audit_logs PRIMARY KEY ("id"),
    CONSTRAINT fk_admin_audit_logs_actor_id FOREIGN KEY ("actor_id") REFERENCES users(id) ON DELETE SET NULL
);

ALTER TABLE admin_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_admin_audit_logs_service ON admin_audit_logs FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_admin_audit_logs_occurred ON admin_audit_logs ("occurred_at");
CREATE INDEX ix_admin_audit_logs_actor ON admin_audit_logs ("actor_id", "occurred_at");

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
    CONSTRAINT fk_projects_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_materials_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_material_versions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_versions_material_version UNIQUE ("material_id", "version_no"),
    CONSTRAINT uq_material_versions_idempotency UNIQUE ("owner_id", "idempotency_key")
);

ALTER TABLE material_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_versions_owner ON material_versions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_material_versions_material ON material_versions ("material_id", "version_no");

-- 教学任务；Requirement、Plan、Execution 都挂在它下面
CREATE TABLE tasks (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "project_id" UUID,
    "title" VARCHAR(300) NOT NULL,
    "objective" TEXT,
    "status" VARCHAR(24) NOT NULL DEFAULT 'draft',
    "state_version" INTEGER NOT NULL DEFAULT 0,
    "state_changed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "current_requirement_version_id" UUID,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_tasks PRIMARY KEY ("id"),
    CONSTRAINT fk_tasks_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tasks_project_id FOREIGN KEY ("project_id") REFERENCES projects(id) ON DELETE RESTRICT,
    CONSTRAINT ck_tasks_status CHECK (status IN ('draft','planning','awaiting_plan_approval','ready','running','completed','needs_attention','cancelling','cancelled'))
);

ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_tasks_owner ON tasks FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_tasks_owner ON tasks ("owner_id", "status", "updated_at") WHERE deleted_at IS NULL;
CREATE INDEX ix_tasks_project ON tasks ("project_id") WHERE deleted_at IS NULL;

-- 需求版本；不可变，Plan 绑定具体版本
CREATE TABLE task_requirement_versions (
    "id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "requirements" JSONB NOT NULL,
    "content_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'draft',
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_task_requirement_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_task_requirement_versions_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_task_requirement_versions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_task_requirement_versions_task_no UNIQUE ("task_id", "version_no"),
    CONSTRAINT ck_task_requirement_versions_status CHECK (status IN ('draft','active','superseded','abandoned'))
);

ALTER TABLE task_requirement_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_requirement_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_task_requirement_versions_owner ON task_requirement_versions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

-- Plan 身份；版本在 agent_plan_versions
CREATE TABLE agent_plans (
    "id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "latest_version_id" UUID,
    "status" VARCHAR(24) NOT NULL DEFAULT 'draft',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_plans PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_plans_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_plans_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT ck_agent_plans_status CHECK (status IN ('draft','awaiting_approval','approved','superseded','abandoned'))
);

ALTER TABLE agent_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_plans_owner ON agent_plans FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_agent_plans_task ON agent_plans ("task_id", "status");

-- Plan 版本；不可变，绑定需求版本
CREATE TABLE agent_plan_versions (
    "id" UUID NOT NULL,
    "plan_id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "version_no" INTEGER NOT NULL,
    "requirement_version_id" UUID NOT NULL,
    "content" JSONB NOT NULL,
    "content_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'draft',
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_plan_versions PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_plan_versions_plan_id FOREIGN KEY ("plan_id") REFERENCES agent_plans(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_plan_versions_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_plan_versions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_plan_versions_requirement_version_id FOREIGN KEY ("requirement_version_id") REFERENCES task_requirement_versions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_agent_plan_versions_plan_no UNIQUE ("plan_id", "version_no"),
    CONSTRAINT ck_agent_plan_versions_status CHECK (status IN ('draft','awaiting_approval','approved','rejected','expired','invalidated','superseded'))
);

ALTER TABLE agent_plan_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_plan_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_plan_versions_owner ON agent_plan_versions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_agent_plan_versions_plan ON agent_plan_versions ("plan_id", "version_no");

-- 单次消费的 Plan 审批；绑定具体版本与 Hash
CREATE TABLE agent_plan_approvals (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "plan_id" UUID NOT NULL,
    "plan_version_id" UUID NOT NULL,
    "plan_content_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'pending',
    "approver_id" UUID,
    "approved_at" TIMESTAMPTZ,
    "expires_at" TIMESTAMPTZ,
    "consumed_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_plan_approvals PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_plan_approvals_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_plan_approvals_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_plan_approvals_plan_id FOREIGN KEY ("plan_id") REFERENCES agent_plans(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_plan_approvals_plan_version_id FOREIGN KEY ("plan_version_id") REFERENCES agent_plan_versions(id) ON DELETE RESTRICT,
    CONSTRAINT ck_agent_plan_approvals_status CHECK (status IN ('pending','approved','rejected','revoked','invalidated','expired')),
    CONSTRAINT ck_agent_plan_approvals_consumed CHECK (consumed_at IS NULL OR status = 'approved')
);

ALTER TABLE agent_plan_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_plan_approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_plan_approvals_owner ON agent_plan_approvals FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_agent_plan_approvals_version ON agent_plan_approvals ("plan_version_id", "status");

-- Plan 内的步骤；DAG 的节点
CREATE TABLE agent_plan_steps (
    "id" UUID NOT NULL,
    "plan_version_id" UUID NOT NULL,
    "step_key" VARCHAR(80) NOT NULL,
    "ordinal" INTEGER NOT NULL,
    "step_type" VARCHAR(40) NOT NULL,
    "title" VARCHAR(300) NOT NULL,
    "input_spec" JSONB,
    "expected_outputs" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_plan_steps PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_plan_steps_plan_version_id FOREIGN KEY ("plan_version_id") REFERENCES agent_plan_versions(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_plan_steps_key UNIQUE ("plan_version_id", "step_key")
);

ALTER TABLE agent_plan_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_plan_steps FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_plan_steps_owner ON agent_plan_steps FOR ALL USING (EXISTS (SELECT 1 FROM agent_plan_versions p WHERE p.id = plan_version_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_plan_versions p WHERE p.id = plan_version_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_plan_steps_version ON agent_plan_steps ("plan_version_id", "ordinal");

-- 步骤依赖边；环检测在应用层，库层保证唯一
CREATE TABLE agent_step_dependencies (
    "id" UUID NOT NULL,
    "plan_version_id" UUID NOT NULL,
    "step_id" UUID NOT NULL,
    "depends_on_step_id" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_step_dependencies PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_step_dependencies_plan_version_id FOREIGN KEY ("plan_version_id") REFERENCES agent_plan_versions(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_step_dependencies_step_id FOREIGN KEY ("step_id") REFERENCES agent_plan_steps(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_step_dependencies_depends_on_step_id FOREIGN KEY ("depends_on_step_id") REFERENCES agent_plan_steps(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_step_dependencies_edge UNIQUE ("step_id", "depends_on_step_id"),
    CONSTRAINT ck_agent_step_dependencies_self CHECK (step_id <> depends_on_step_id)
);

ALTER TABLE agent_step_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_step_dependencies FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_step_dependencies_owner ON agent_step_dependencies FOR ALL USING (EXISTS (SELECT 1 FROM agent_plan_versions p WHERE p.id = plan_version_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_plan_versions p WHERE p.id = plan_version_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_step_dependencies_dep ON agent_step_dependencies ("depends_on_step_id");

-- 插件注册表；Plugin Manifest Hash 来自这里
CREATE TABLE agent_runtime_plugins (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "version" VARCHAR(64) NOT NULL,
    "manifest" JSONB NOT NULL,
    "manifest_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_runtime_plugins PRIMARY KEY ("id"),
    CONSTRAINT uq_agent_runtime_plugins_key_version UNIQUE ("key", "version"),
    CONSTRAINT ck_agent_runtime_plugins_status CHECK (status IN ('active','disabled'))
);

ALTER TABLE agent_runtime_plugins ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runtime_plugins FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_runtime_plugins_service ON agent_runtime_plugins FOR ALL USING (true) WITH CHECK (true);

-- 工具定义；业务权威归 Chilon，不归插件
CREATE TABLE agent_tool_definitions (
    "id" UUID NOT NULL,
    "key" VARCHAR(80) NOT NULL,
    "version" VARCHAR(32) NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "plugin_id" UUID,
    "input_schema" JSONB,
    "output_schema" JSONB,
    "side_effect_level" VARCHAR(16) NOT NULL DEFAULT 'read',
    "requires_approval" BOOLEAN NOT NULL DEFAULT false,
    "is_enabled" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_tool_definitions PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_tool_definitions_plugin_id FOREIGN KEY ("plugin_id") REFERENCES agent_runtime_plugins(id) ON DELETE RESTRICT,
    CONSTRAINT uq_agent_tool_definitions_key_version UNIQUE ("key", "version"),
    CONSTRAINT ck_agent_tool_definitions_side_effect CHECK (side_effect_level IN ('read','write','irreversible'))
);

ALTER TABLE agent_tool_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tool_definitions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_tool_definitions_service ON agent_tool_definitions FOR ALL USING (true) WITH CHECK (true);

-- 教师可用的工具授权；Tool Call 前置校验
CREATE TABLE agent_tool_grants (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "tool_definition_id" UUID NOT NULL,
    "capability" VARCHAR(64) NOT NULL,
    "granted_by" UUID,
    "granted_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "revoked_at" TIMESTAMPTZ,
    CONSTRAINT pk_agent_tool_grants PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_tool_grants_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_tool_grants_tool_definition_id FOREIGN KEY ("tool_definition_id") REFERENCES agent_tool_definitions(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_tool_grants_owner_tool UNIQUE ("owner_id", "tool_definition_id")
);

ALTER TABLE agent_tool_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tool_grants FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_tool_grants_owner ON agent_tool_grants FOR SELECT USING (owner_id = public.app_current_user_id());
CREATE POLICY pol_agent_tool_grants_owner_all ON agent_tool_grants FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

-- 执行；持有 Lease 与 Fencing Token
CREATE TABLE agent_executions (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "task_id" UUID NOT NULL,
    "plan_version_id" UUID NOT NULL,
    "plan_approval_id" UUID NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'queued',
    "state_version" INTEGER NOT NULL DEFAULT 0,
    "state_changed_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "lease_owner_id" VARCHAR(120),
    "lease_expires_at" TIMESTAMPTZ,
    "heartbeat_at" TIMESTAMPTZ,
    "fencing_token" BIGINT NOT NULL DEFAULT 0,
    "idempotency_key" VARCHAR(255),
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "error_code" VARCHAR(80),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_executions PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_executions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_executions_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_executions_plan_version_id FOREIGN KEY ("plan_version_id") REFERENCES agent_plan_versions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_executions_plan_approval_id FOREIGN KEY ("plan_approval_id") REFERENCES agent_plan_approvals(id) ON DELETE RESTRICT,
    CONSTRAINT ck_agent_executions_status CHECK (status IN ('queued','starting','running','pause_requested','paused','cancel_requested','cancelling','outcome_unknown','succeeded','failed','cancelled','superseded')),
    CONSTRAINT ck_agent_executions_fencing CHECK (fencing_token >= 0)
);

ALTER TABLE agent_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_executions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_executions_owner ON agent_executions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_agent_executions_task ON agent_executions ("task_id", "status");
CREATE INDEX ix_agent_executions_lease ON agent_executions ("status", "lease_expires_at") WHERE status IN ('starting','running','paused');
CREATE UNIQUE INDEX ix_agent_executions_idempotency ON agent_executions ("owner_id", "idempotency_key") WHERE idempotency_key IS NOT NULL;

-- Execution 与 Runtime Session 的映射；一次执行可有多轮
CREATE TABLE agent_runs (
    "id" UUID NOT NULL,
    "execution_id" UUID NOT NULL,
    "ordinal" INTEGER NOT NULL,
    "harness_session_id" VARCHAR(120),
    "model" VARCHAR(120),
    "prompt_version" VARCHAR(64),
    "status" VARCHAR(24) NOT NULL DEFAULT 'starting',
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_runs PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_runs_execution_id FOREIGN KEY ("execution_id") REFERENCES agent_executions(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_runs_execution_ordinal UNIQUE ("execution_id", "ordinal"),
    CONSTRAINT ck_agent_runs_status CHECK (status IN ('starting','running','interrupted','completed','failed','lost','superseded'))
);

ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_runs_owner ON agent_runs FOR ALL USING (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_runs_execution ON agent_runs ("execution_id", "ordinal");

-- 单个 Plan 步骤的执行
CREATE TABLE agent_step_executions (
    "id" UUID NOT NULL,
    "execution_id" UUID NOT NULL,
    "plan_step_id" UUID NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'pending',
    "attempt" SMALLINT NOT NULL DEFAULT 0,
    "output" JSONB,
    "error_code" VARCHAR(80),
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_step_executions PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_step_executions_execution_id FOREIGN KEY ("execution_id") REFERENCES agent_executions(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_step_executions_plan_step_id FOREIGN KEY ("plan_step_id") REFERENCES agent_plan_steps(id) ON DELETE RESTRICT,
    CONSTRAINT uq_agent_step_executions_step UNIQUE ("execution_id", "plan_step_id"),
    CONSTRAINT ck_agent_step_executions_status CHECK (status IN ('pending','ready','running','paused','succeeded','failed','blocked','skipped','cancelled','superseded'))
);

ALTER TABLE agent_step_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_step_executions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_step_executions_owner ON agent_step_executions FOR ALL USING (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_step_executions_execution ON agent_step_executions ("execution_id", "status");

-- 工具调用；带幂等键与参数 Hash
CREATE TABLE agent_tool_executions (
    "id" UUID NOT NULL,
    "execution_id" UUID NOT NULL,
    "step_execution_id" UUID,
    "tool_definition_id" UUID NOT NULL,
    "tool_version" VARCHAR(32) NOT NULL,
    "idempotency_key" VARCHAR(255) NOT NULL,
    "args_hash" CHAR(64) NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'requested',
    "result" JSONB,
    "result_hash" CHAR(64),
    "error_code" VARCHAR(80),
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_tool_executions PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_tool_executions_execution_id FOREIGN KEY ("execution_id") REFERENCES agent_executions(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_tool_executions_step_execution_id FOREIGN KEY ("step_execution_id") REFERENCES agent_step_executions(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_tool_executions_tool_definition_id FOREIGN KEY ("tool_definition_id") REFERENCES agent_tool_definitions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_agent_tool_executions_idempotency UNIQUE ("idempotency_key"),
    CONSTRAINT ck_agent_tool_executions_status CHECK (status IN ('requested','authorizing','authorized','rejected','dispatching','running','succeeded','failed','cancelled','outcome_unknown'))
);

ALTER TABLE agent_tool_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tool_executions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_tool_executions_owner ON agent_tool_executions FOR ALL USING (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_tool_executions_execution ON agent_tool_executions ("execution_id", "status");
CREATE INDEX ix_agent_tool_executions_step ON agent_tool_executions ("step_execution_id") WHERE step_execution_id IS NOT NULL;

-- Harness Runtime 事件；与业务事件分离，原样保留
CREATE TABLE agent_runtime_events (
    "id" UUID NOT NULL,
    "agent_run_id" UUID NOT NULL,
    "seq" BIGINT NOT NULL,
    "event_type" VARCHAR(80) NOT NULL,
    "payload" JSONB NOT NULL,
    "payload_hash" CHAR(64) NOT NULL,
    "occurred_at" TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_agent_runtime_events PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_runtime_events_agent_run_id FOREIGN KEY ("agent_run_id") REFERENCES agent_runs(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_runtime_events_run_seq UNIQUE ("agent_run_id", "seq")
);

ALTER TABLE agent_runtime_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runtime_events FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_runtime_events_owner ON agent_runtime_events FOR ALL USING (EXISTS (SELECT 1 FROM agent_runs  JOIN agent_executions ON agent_executions.id = agent_runs.execution_id WHERE agent_runs.id = agent_run_id AND agent_executions.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_runs  JOIN agent_executions ON agent_executions.id = agent_runs.execution_id WHERE agent_runs.id = agent_run_id AND agent_executions.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_runtime_events_run ON agent_runtime_events ("agent_run_id", "seq");

-- Chilon 业务执行事件；append-only，同事务写 Outbox
CREATE TABLE agent_execution_events (
    "id" UUID NOT NULL,
    "execution_id" UUID NOT NULL,
    "seq" BIGINT NOT NULL,
    "event_type" VARCHAR(80) NOT NULL,
    "from_status" VARCHAR(24),
    "to_status" VARCHAR(24),
    "actor_type" VARCHAR(16) NOT NULL,
    "actor_id" UUID,
    "fencing_token" BIGINT,
    "payload" JSONB,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_execution_events PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_execution_events_execution_id FOREIGN KEY ("execution_id") REFERENCES agent_executions(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_execution_events_exec_seq UNIQUE ("execution_id", "seq"),
    CONSTRAINT ck_agent_execution_events_actor CHECK (actor_type IN ('teacher','system','worker'))
);

ALTER TABLE agent_execution_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_execution_events FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_execution_events_owner ON agent_execution_events FOR ALL USING (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM agent_executions p WHERE p.id = execution_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_agent_execution_events_execution ON agent_execution_events ("execution_id", "seq");

-- 事务性发件箱；物理归 K011，逻辑上为跨模块共享设施
CREATE TABLE outbox_events (
    "id" UUID NOT NULL,
    "event_id" UUID NOT NULL,
    "aggregate_type" VARCHAR(64) NOT NULL,
    "aggregate_id" UUID NOT NULL,
    "event_type" VARCHAR(80) NOT NULL,
    "payload" JSONB NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'pending',
    "attempts" SMALLINT NOT NULL DEFAULT 0,
    "available_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "delivered_at" TIMESTAMPTZ,
    "last_error" TEXT,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_outbox_events PRIMARY KEY ("id"),
    CONSTRAINT uq_outbox_events_event_id UNIQUE ("event_id"),
    CONSTRAINT ck_outbox_events_status CHECK (status IN ('pending','delivered','failed','dead_letter'))
);

ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_outbox_events_rw ON outbox_events FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_outbox_events_dispatch ON outbox_events ("status", "available_at") WHERE status IN ('pending','failed');
CREATE INDEX ix_outbox_events_aggregate ON outbox_events ("aggregate_type", "aggregate_id");

-- 交流上下文；Task 可有多个对话
CREATE TABLE conversations (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "task_id" UUID,
    "title" VARCHAR(300),
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "last_message_at" TIMESTAMPTZ,
    "created_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_conversations PRIMARY KEY ("id"),
    CONSTRAINT fk_conversations_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_conversations_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE SET NULL,
    CONSTRAINT ck_conversations_status CHECK (status IN ('active','archived'))
);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversations_owner ON conversations FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_conversations_owner ON conversations ("owner_id", "updated_at") WHERE deleted_at IS NULL;
CREATE INDEX ix_conversations_task ON conversations ("task_id") WHERE task_id IS NOT NULL;

-- 教师与 Agent 可见的消息；工具调用不是 Message Role
CREATE TABLE conversation_messages (
    "id" UUID NOT NULL,
    "conversation_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "seq" BIGINT NOT NULL,
    "role" VARCHAR(16) NOT NULL,
    "content_blocks" JSONB NOT NULL,
    "content_schema_version" VARCHAR(20) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'completed',
    "error_code" VARCHAR(80),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "completed_at" TIMESTAMPTZ,
    CONSTRAINT pk_conversation_messages PRIMARY KEY ("id"),
    CONSTRAINT fk_conversation_messages_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_conversation_messages_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_conversation_messages_seq UNIQUE ("conversation_id", "seq"),
    CONSTRAINT ck_conversation_messages_role CHECK (role IN ('user','assistant','system')),
    CONSTRAINT ck_conversation_messages_status CHECK (status IN ('streaming','completed','interrupted','failed'))
);

ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversation_messages_owner ON conversation_messages FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_conversation_messages_conv ON conversation_messages ("conversation_id", "seq");

-- 追加式事件流；SSE Last-Event-ID 的事实来源
CREATE TABLE conversation_events (
    "id" UUID NOT NULL,
    "conversation_id" UUID NOT NULL,
    "seq" BIGINT NOT NULL,
    "event_type" VARCHAR(80) NOT NULL,
    "payload" JSONB NOT NULL,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_conversation_events PRIMARY KEY ("id"),
    CONSTRAINT fk_conversation_events_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT uq_conversation_events_seq UNIQUE ("conversation_id", "seq")
);

ALTER TABLE conversation_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_events FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversation_events_owner ON conversation_events FOR ALL USING (EXISTS (SELECT 1 FROM conversations p WHERE p.id = conversation_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM conversations p WHERE p.id = conversation_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_conversation_events_conv ON conversation_events ("conversation_id", "seq");

-- 教师可理解的进度；可更新，不是 append-only 事件
CREATE TABLE agent_activities (
    "id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "conversation_id" UUID,
    "task_id" UUID,
    "execution_id" UUID,
    "label" VARCHAR(300) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'running',
    "progress" SMALLINT,
    "detail" JSONB,
    "started_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_activities PRIMARY KEY ("id"),
    CONSTRAINT fk_agent_activities_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_activities_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_activities_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE SET NULL,
    CONSTRAINT fk_agent_activities_execution_id FOREIGN KEY ("execution_id") REFERENCES agent_executions(id) ON DELETE SET NULL,
    CONSTRAINT ck_agent_activities_status CHECK (status IN ('pending','running','done','failed','cancelled')),
    CONSTRAINT ck_agent_activities_progress CHECK (progress IS NULL OR (progress >= 0 AND progress <= 100))
);

ALTER TABLE agent_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_activities FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_agent_activities_owner ON agent_activities FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_agent_activities_conversation ON agent_activities ("conversation_id", "started_at");

-- 对话附件；内容存对象存储，库内只存引用
CREATE TABLE conversation_attachments (
    "id" UUID NOT NULL,
    "conversation_id" UUID NOT NULL,
    "message_id" UUID,
    "owner_id" UUID NOT NULL,
    "storage_key" VARCHAR(500) NOT NULL,
    "mime_type" VARCHAR(120) NOT NULL,
    "file_size_bytes" BIGINT NOT NULL,
    "checksum_sha256" CHAR(64) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_conversation_attachments PRIMARY KEY ("id"),
    CONSTRAINT fk_conversation_attachments_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_conversation_attachments_message_id FOREIGN KEY ("message_id") REFERENCES conversation_messages(id) ON DELETE SET NULL,
    CONSTRAINT fk_conversation_attachments_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT
);

ALTER TABLE conversation_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_attachments FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversation_attachments_owner ON conversation_attachments FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

CREATE INDEX ix_conversation_attachments_conv ON conversation_attachments ("conversation_id");

-- 对话参与者；区分教师、Agent 与系统
CREATE TABLE conversation_participants (
    "id" UUID NOT NULL,
    "conversation_id" UUID NOT NULL,
    "participant_type" VARCHAR(16) NOT NULL,
    "participant_id" UUID,
    "role" VARCHAR(32),
    "joined_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_conversation_participants PRIMARY KEY ("id"),
    CONSTRAINT fk_conversation_participants_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT uq_conversation_participants UNIQUE ("conversation_id", "participant_type"),
    CONSTRAINT ck_conversation_participants_type CHECK (participant_type IN ('teacher','agent','system'))
);

ALTER TABLE conversation_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_participants FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversation_participants_owner ON conversation_participants FOR ALL USING (EXISTS (SELECT 1 FROM conversations p WHERE p.id = conversation_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM conversations p WHERE p.id = conversation_id AND p.owner_id = public.app_current_user_id()));

-- 每教师每对话的读取与投递水位；SSE 重连与对账用
CREATE TABLE conversation_cursors (
    "id" UUID NOT NULL,
    "conversation_id" UUID NOT NULL,
    "owner_id" UUID NOT NULL,
    "last_read_event_seq" BIGINT NOT NULL DEFAULT 0,
    "last_delivered_event_seq" BIGINT NOT NULL DEFAULT 0,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_conversation_cursors PRIMARY KEY ("id"),
    CONSTRAINT fk_conversation_cursors_conversation_id FOREIGN KEY ("conversation_id") REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_conversation_cursors_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_conversation_cursors_owner UNIQUE ("conversation_id", "owner_id"),
    CONSTRAINT ck_conversation_cursors_monotonic CHECK (last_read_event_seq >= 0 AND last_delivered_event_seq >= 0)
);

ALTER TABLE conversation_cursors ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_cursors FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_conversation_cursors_owner ON conversation_cursors FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

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
    CONSTRAINT fk_material_drafts_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_material_draft_revisions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_material_draft_revisions_parent_revision_id FOREIGN KEY ("parent_revision_id") REFERENCES material_draft_revisions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_material_draft_revisions_draft_no UNIQUE ("draft_id", "revision_no"),
    CONSTRAINT ck_material_draft_revisions_origin CHECK (change_origin IN ('teacher_edit','chat_revision','agent_generation','rebase','restore','import')),
    CONSTRAINT ck_material_draft_revisions_class CHECK (revision_class IN ('checkpoint','autosave'))
);

ALTER TABLE material_draft_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE material_draft_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_material_draft_revisions_owner ON material_draft_revisions FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

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
CREATE POLICY pol_document_schema_definitions_service ON document_schema_definitions FOR ALL USING (true) WITH CHECK (true);

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
    CONSTRAINT fk_material_references_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_task_material_links_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_task_material_links_task_id FOREIGN KEY ("task_id") REFERENCES tasks(id) ON DELETE RESTRICT,
    CONSTRAINT fk_task_material_links_material_id FOREIGN KEY ("material_id") REFERENCES materials(id) ON DELETE RESTRICT,
    CONSTRAINT fk_task_material_links_material_version_id FOREIGN KEY ("material_version_id") REFERENCES material_versions(id) ON DELETE RESTRICT,
    CONSTRAINT uq_task_material_links_task_version UNIQUE ("task_id", "material_version_id"),
    CONSTRAINT ck_task_material_links_relation CHECK (relation IN ('deliverable','reference'))
);

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
    CONSTRAINT fk_material_publication_approvals_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_material_exports_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_quality_rules_service ON quality_rules FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_rule_versions_service ON quality_rule_versions FOR ALL USING (true) WITH CHECK (true);

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
    CONSTRAINT fk_quality_check_runs_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_quality_check_rule_snapshots_owner ON quality_check_rule_snapshots FOR ALL USING (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id()));

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
CREATE POLICY pol_quality_check_results_owner ON quality_check_results FOR ALL USING (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id()));

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
    CONSTRAINT fk_quality_issues_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_quality_evidence_owner ON quality_evidence FOR ALL USING (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM quality_check_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id()));

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
    CONSTRAINT fk_math_validation_runs_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_math_validation_evidence_owner ON math_validation_evidence FOR ALL USING (EXISTS (SELECT 1 FROM math_validation_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM math_validation_runs p WHERE p.id = run_id AND p.owner_id = public.app_current_user_id()));

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
    CONSTRAINT fk_quality_issue_feedback_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
    CONSTRAINT fk_quality_issue_resolutions_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_quality_datasets_service ON quality_datasets FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_dataset_versions_service ON quality_dataset_versions FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_dataset_items_service ON quality_dataset_items FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_evaluations_service ON quality_evaluations FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_evaluation_runs_service ON quality_evaluation_runs FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_evaluation_results_service ON quality_evaluation_results FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_metrics_service ON quality_metrics FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_metric_observations_service ON quality_metric_observations FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_alerts_service ON quality_alerts FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_alert_events_service ON quality_alert_events FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_releases_service ON quality_releases FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_release_approvals_service ON quality_release_approvals FOR ALL USING (true) WITH CHECK (true);

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
CREATE POLICY pol_quality_release_events_service ON quality_release_events FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_quality_release_events_release ON quality_release_events ("release_id", "occurred_at");

-- 高风险管理员操作的申请；审批绑定版本与参数 Hash
CREATE TABLE admin_operation_requests (
    "id" UUID NOT NULL,
    "request_type" VARCHAR(80) NOT NULL,
    "request_version" INTEGER NOT NULL DEFAULT 1,
    "parameters" JSONB NOT NULL,
    "parameters_hash" CHAR(64) NOT NULL,
    "target_type" VARCHAR(64) NOT NULL,
    "target_id" UUID,
    "target_owner_id" UUID,
    "status" VARCHAR(24) NOT NULL DEFAULT 'pending',
    "justification" TEXT,
    "requested_by" UUID NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_admin_operation_requests PRIMARY KEY ("id"),
    CONSTRAINT fk_admin_operation_requests_requested_by FOREIGN KEY ("requested_by") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT ck_admin_operation_requests_status CHECK (status IN ('pending','approved','rejected','executing','executed','failed','cancelled','expired'))
);

ALTER TABLE admin_operation_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_operation_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_admin_operation_requests_service ON admin_operation_requests FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_admin_operation_requests_status ON admin_operation_requests ("status", "created_at");
CREATE INDEX ix_admin_operation_requests_target ON admin_operation_requests ("target_type", "target_id");

-- 管理员操作审批；绑定 request_version 与 parameters_hash
CREATE TABLE admin_operation_approvals (
    "id" UUID NOT NULL,
    "request_id" UUID NOT NULL,
    "request_version" INTEGER NOT NULL,
    "parameters_hash" CHAR(64) NOT NULL,
    "policy_version" VARCHAR(64) NOT NULL,
    "decision" VARCHAR(16) NOT NULL,
    "approver_id" UUID NOT NULL,
    "reason" TEXT,
    "decided_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "expires_at" TIMESTAMPTZ,
    CONSTRAINT pk_admin_operation_approvals PRIMARY KEY ("id"),
    CONSTRAINT fk_admin_operation_approvals_request_id FOREIGN KEY ("request_id") REFERENCES admin_operation_requests(id) ON DELETE CASCADE,
    CONSTRAINT fk_admin_operation_approvals_approver_id FOREIGN KEY ("approver_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT ck_admin_operation_approvals_decision CHECK (decision IN ('approved','rejected'))
);

ALTER TABLE admin_operation_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_operation_approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_admin_operation_approvals_service ON admin_operation_approvals FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_admin_operation_approvals_request ON admin_operation_approvals ("request_id", "decision");

-- 执行记录；执行前重新校验审批、Hash 与权限
CREATE TABLE admin_operation_executions (
    "id" UUID NOT NULL,
    "request_id" UUID NOT NULL,
    "approval_id" UUID NOT NULL,
    "status" VARCHAR(24) NOT NULL DEFAULT 'queued',
    "idempotency_key" VARCHAR(255) NOT NULL,
    "attempt" SMALLINT NOT NULL DEFAULT 0,
    "result" JSONB,
    "error_code" VARCHAR(80),
    "executed_by" UUID NOT NULL,
    "started_at" TIMESTAMPTZ,
    "finished_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_admin_operation_executions PRIMARY KEY ("id"),
    CONSTRAINT fk_admin_operation_executions_request_id FOREIGN KEY ("request_id") REFERENCES admin_operation_requests(id) ON DELETE CASCADE,
    CONSTRAINT fk_admin_operation_executions_approval_id FOREIGN KEY ("approval_id") REFERENCES admin_operation_approvals(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_operation_executions_executed_by FOREIGN KEY ("executed_by") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_admin_operation_executions_idempotency UNIQUE ("idempotency_key"),
    CONSTRAINT ck_admin_operation_executions_status CHECK (status IN ('queued','running','succeeded','failed','cancelled','outcome_unknown'))
);

ALTER TABLE admin_operation_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_operation_executions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_admin_operation_executions_service ON admin_operation_executions FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_admin_operation_executions_request ON admin_operation_executions ("request_id", "status");

-- 管理侧安全事件；append-only，不可抵赖
CREATE TABLE admin_security_events (
    "id" UUID NOT NULL,
    "event_type" VARCHAR(80) NOT NULL,
    "actor_id" UUID,
    "request_id" UUID,
    "target_type" VARCHAR(64),
    "target_id" UUID,
    "target_owner_id" UUID,
    "detail" JSONB,
    "occurred_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_admin_security_events PRIMARY KEY ("id"),
    CONSTRAINT fk_admin_security_events_actor_id FOREIGN KEY ("actor_id") REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_admin_security_events_request_id FOREIGN KEY ("request_id") REFERENCES admin_operation_requests(id) ON DELETE SET NULL
);

ALTER TABLE admin_security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_security_events FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_admin_security_events_service ON admin_security_events FOR ALL USING (true) WITH CHECK (true);

CREATE INDEX ix_admin_security_events_occurred ON admin_security_events ("occurred_at");
CREATE INDEX ix_admin_security_events_actor ON admin_security_events ("actor_id", "occurred_at");

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
    CONSTRAINT fk_knowledge_categories_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT uq_knowledge_categories_scope_owner_key UNIQUE ("scope", "owner_id", "key"),
    CONSTRAINT ck_knowledge_categories_scope_owner CHECK ((scope = 'platform' AND owner_id IS NULL) OR (scope = 'teacher' AND owner_id IS NOT NULL)),
    CONSTRAINT ck_knowledge_categories_source_type CHECK (source_type IS NULL OR source_type IN ('textbook','workbook','gaokao_paper','mock_exam','other'))
);

ALTER TABLE knowledge_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_categories FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_knowledge_categories_select ON knowledge_categories FOR SELECT USING (scope = 'platform' OR owner_id = public.app_current_user_id());
CREATE POLICY pol_knowledge_categories_owner_all ON knowledge_categories FOR ALL USING (owner_id = public.app_current_user_id()) WITH CHECK (owner_id = public.app_current_user_id());

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
    CONSTRAINT fk_knowledge_sources_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT,
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
CREATE POLICY pol_knowledge_document_versions_read ON knowledge_document_versions FOR SELECT USING (EXISTS (SELECT 1 FROM knowledge_sources s WHERE s.id = source_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));
CREATE POLICY pol_knowledge_document_versions_write ON knowledge_document_versions FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_sources s WHERE s.id = source_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_sources s WHERE s.id = source_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
CREATE POLICY pol_knowledge_chunks_read ON knowledge_chunks FOR SELECT USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));
CREATE POLICY pol_knowledge_chunks_write ON knowledge_chunks FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
    "current_paper_question_type" VARCHAR(32),
    "current_knowledge_points" TEXT[],
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT pk_knowledge_questions PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_questions_document_version_id FOREIGN KEY ("document_version_id") REFERENCES knowledge_document_versions(id) ON DELETE CASCADE,
    CONSTRAINT uq_knowledge_questions_version_no UNIQUE ("document_version_id", "question_no"),
    CONSTRAINT ck_knowledge_questions_paper_type CHECK (current_paper_question_type IN ('single_choice','multiple_choice','fill_blank','free_response')),
    CONSTRAINT ck_knowledge_questions_score CHECK (score IS NULL OR score >= 0),
    CONSTRAINT ck_knowledge_questions_segmentation CHECK (segmentation_status IN ('auto','accepted','corrected','rejected') AND segmentation_source IN ('rule','model','teacher'))
);

ALTER TABLE knowledge_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_questions FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_knowledge_questions_read ON knowledge_questions FOR SELECT USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));
CREATE POLICY pol_knowledge_questions_write ON knowledge_questions FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
CREATE POLICY pol_knowledge_annotations_owner ON knowledge_annotations FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_questions  JOIN knowledge_document_versions ON knowledge_document_versions.id = knowledge_questions.document_version_id JOIN knowledge_sources ON knowledge_sources.id = knowledge_document_versions.source_id WHERE knowledge_questions.id = question_id AND knowledge_sources.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_questions  JOIN knowledge_document_versions ON knowledge_document_versions.id = knowledge_questions.document_version_id JOIN knowledge_sources ON knowledge_sources.id = knowledge_document_versions.source_id WHERE knowledge_questions.id = question_id AND knowledge_sources.owner_id = public.app_current_user_id()));

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
CREATE POLICY pol_knowledge_ingestion_runs_write ON knowledge_ingestion_runs FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
CREATE POLICY pol_knowledge_reviews_write ON knowledge_reviews FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
CREATE POLICY pol_knowledge_indexing_jobs_write ON knowledge_indexing_jobs FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id()))) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_document_versions d JOIN knowledge_sources s ON s.id = d.source_id WHERE d.id = document_version_id AND (s.scope = 'platform' OR s.owner_id = public.app_current_user_id())));

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
    CONSTRAINT pk_knowledge_retrieval_runs PRIMARY KEY ("id"),
    CONSTRAINT fk_knowledge_retrieval_runs_owner_id FOREIGN KEY ("owner_id") REFERENCES users(id) ON DELETE RESTRICT
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
CREATE POLICY pol_knowledge_retrieval_results_owner ON knowledge_retrieval_results FOR ALL USING (EXISTS (SELECT 1 FROM knowledge_retrieval_runs p WHERE p.id = retrieval_run_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM knowledge_retrieval_runs p WHERE p.id = retrieval_run_id AND p.owner_id = public.app_current_user_id()));

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
CREATE POLICY pol_material_knowledge_citations_owner ON material_knowledge_citations FOR ALL USING (EXISTS (SELECT 1 FROM material_versions p WHERE p.id = material_version_id AND p.owner_id = public.app_current_user_id())) WITH CHECK (EXISTS (SELECT 1 FROM material_versions p WHERE p.id = material_version_id AND p.owner_id = public.app_current_user_id()));

CREATE INDEX ix_material_knowledge_citations_version ON material_knowledge_citations ("material_version_id");
CREATE INDEX ix_material_knowledge_citations_source ON material_knowledge_citations ("source_id");
CREATE INDEX ix_material_knowledge_citations_question ON material_knowledge_citations ("question_id") WHERE question_id IS NOT NULL;

-- Deferred foreign keys (circular or forward references)
ALTER TABLE materials ADD CONSTRAINT fk_materials_current_version_id FOREIGN KEY ("current_version_id") REFERENCES material_versions(id) ON DELETE SET NULL;
ALTER TABLE material_versions ADD CONSTRAINT fk_material_versions_source_draft_revision_id FOREIGN KEY ("source_draft_revision_id") REFERENCES material_draft_revisions(id) ON DELETE SET NULL;
ALTER TABLE material_versions ADD CONSTRAINT fk_material_versions_publication_approval_id FOREIGN KEY ("publication_approval_id") REFERENCES material_publication_approvals(id) ON DELETE RESTRICT;
ALTER TABLE tasks ADD CONSTRAINT fk_tasks_current_requirement_version_id FOREIGN KEY ("current_requirement_version_id") REFERENCES task_requirement_versions(id) ON DELETE SET NULL;
ALTER TABLE agent_plans ADD CONSTRAINT fk_agent_plans_latest_version_id FOREIGN KEY ("latest_version_id") REFERENCES agent_plan_versions(id) ON DELETE SET NULL;
ALTER TABLE material_drafts ADD CONSTRAINT fk_material_drafts_current_revision_id FOREIGN KEY ("current_revision_id") REFERENCES material_draft_revisions(id) ON DELETE SET NULL;

-- Grants are intentionally not generated: they depend on deployment roles.
-- Runtime role must not own tables or have BYPASSRLS (see §10.2).
