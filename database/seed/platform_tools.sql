-- Platform tool definitions.
--
-- These are platform rows (`agent_tool_definitions` is service-scoped), so they are
-- deployed by an administrator, not created by a teacher. Without them a new account
-- has nothing to be granted and the product cannot plan anything.
--
-- Every deployment must apply this file once. It is idempotent.

INSERT INTO agent_tool_definitions (id, key, version, name, side_effect_level, is_enabled)
VALUES
    (gen_random_uuid(), 'knowledge.search',       '1.0.0', '知识库检索',   'read',  true),
    (gen_random_uuid(), 'content.generate',       '1.0.0', '内容生成',     'write', true),
    (gen_random_uuid(), 'quality.check',          '1.0.0', '质量检查',     'read',  true),
    (gen_random_uuid(), 'material.create_draft',  '1.0.0', '材料落库',     'write', true)
ON CONFLICT (key, version) DO NOTHING;
