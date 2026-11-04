-- Row-level security isolation test.
--
-- Runs against the generated schema. Asserts three separate properties, because
-- "the other teacher's data is hidden" is not one behaviour but three:
--   1. SELECT  does not return another owner's rows
--   2. UPDATE  cannot modify another owner's rows
--   3. INSERT  cannot create a row owned by someone else
--
-- A policy that only gets SELECT right still lets a bug write across tenants.

\set ON_ERROR_STOP on

-- Application role: no superuser, no BYPASSRLS. Superusers ignore RLS entirely,
-- so testing as `postgres` would prove nothing.
DROP ROLE IF EXISTS chilon_app_test;
CREATE ROLE chilon_app_test NOLOGIN;
GRANT USAGE ON SCHEMA public TO chilon_app_test;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO chilon_app_test;

-- Two teachers, seeded as superuser (which bypasses RLS).
DO $$
DECLARE
    alice uuid := '11111111-1111-1111-1111-111111111111';
    bob   uuid := '22222222-2222-2222-2222-222222222222';
BEGIN
    INSERT INTO users (id, username, display_name) VALUES
        (alice, 'alice', 'Alice'),
        (bob,   'bob',   'Bob');

    INSERT INTO projects (id, owner_id, name, created_by) VALUES
        ('a0000000-0000-0000-0000-000000000001', alice, 'Alice 的项目', alice),
        ('b0000000-0000-0000-0000-000000000001', bob,   'Bob 的项目',   bob);

    INSERT INTO materials (id, owner_id, title, created_by) VALUES
        ('a0000000-0000-0000-0000-000000000002', alice, 'Alice 的材料', alice),
        ('b0000000-0000-0000-0000-000000000002', bob,   'Bob 的材料',   bob);
END $$;

-- --- as Alice ------------------------------------------------------------
SET ROLE chilon_app_test;
SELECT set_config('app.current_user_id', '11111111-1111-1111-1111-111111111111', false);

DO $$
DECLARE
    n_materials int;
    n_projects  int;
    n_users     int;
    touched     int;
    blocked     boolean := false;
BEGIN
    SELECT count(*) INTO n_materials FROM materials;
    IF n_materials <> 1 THEN
        RAISE EXCEPTION 'SELECT leaked: Alice sees % materials, expected 1', n_materials;
    END IF;

    SELECT count(*) INTO n_projects FROM projects;
    IF n_projects <> 1 THEN
        RAISE EXCEPTION 'SELECT leaked: Alice sees % projects, expected 1', n_projects;
    END IF;

    SELECT count(*) INTO n_users FROM users;
    IF n_users <> 1 THEN
        RAISE EXCEPTION 'SELECT leaked: Alice sees % users, expected only herself', n_users;
    END IF;

    -- UPDATE isolation: Bob's row must not be reachable
    UPDATE materials SET title = 'hijacked' WHERE id = 'b0000000-0000-0000-0000-000000000002';
    GET DIAGNOSTICS touched = ROW_COUNT;
    IF touched <> 0 THEN
        RAISE EXCEPTION 'UPDATE leaked: Alice modified % of Bob''s materials', touched;
    END IF;

    -- INSERT guard: a row owned by Bob must be rejected by WITH CHECK
    BEGIN
        INSERT INTO materials (id, owner_id, title, created_by)
        VALUES (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', 'forged', '22222222-2222-2222-2222-222222222222');
    EXCEPTION WHEN insufficient_privilege THEN
        blocked := true;
    END;
    IF NOT blocked THEN
        RAISE EXCEPTION 'INSERT leaked: Alice created a material owned by Bob';
    END IF;

    RAISE NOTICE 'Alice: select/update/insert all confined to her own rows';
END $$;

RESET ROLE;

-- --- as Bob (independence check) ----------------------------------------
SET ROLE chilon_app_test;
SELECT set_config('app.current_user_id', '22222222-2222-2222-2222-222222222222', false);

DO $$
DECLARE
    v_count int;
    v_title text;
BEGIN
    SELECT count(*), min(materials.title) INTO v_count, v_title FROM materials;
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'SELECT leaked: Bob sees % materials, expected 1', v_count;
    END IF;
    IF v_title = 'hijacked' THEN
        RAISE EXCEPTION 'Bob''s material was modified by Alice';
    END IF;
    RAISE NOTICE 'Bob: sees exactly one material and it is untouched';
END $$;

RESET ROLE;

-- --- no context at all --------------------------------------------------
-- Setting the GUC is session-level here (is_local = false), so RESET ROLE does
-- NOT clear it. The application always uses is_local = true, which is exactly
-- why: a leaked session-level context is how one request reads another's rows.
-- Clearing it to '' makes nullif(...)::uuid return NULL, i.e. "no identity".
SET ROLE chilon_app_test;
SELECT set_config('app.current_user_id', '', false);
DO $$
DECLARE
    n_materials int;
    n_projects  int;
BEGIN
    SELECT count(*) INTO n_materials FROM materials;
    IF n_materials <> 0 THEN
        RAISE EXCEPTION 'no-context session saw % materials; a background job could read everyone', n_materials;
    END IF;
    SELECT count(*) INTO n_projects FROM projects;
    IF n_projects <> 0 THEN
        RAISE EXCEPTION 'no-context session saw % projects', n_projects;
    END IF;
    RAISE NOTICE 'no user context: zero rows visible, as designed';
END $$;

RESET ROLE;
