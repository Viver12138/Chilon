-- Structural smoke test for the generated DDL.
--
-- Expected counts are passed in as psql variables so the test stays in sync with
-- the manifest instead of hard-coding numbers that drift.
--
-- psql does not substitute variables inside dollar-quoted blocks, so the values
-- are stored as custom settings first and read back with current_setting().

SET test.expected_tables = :'expected_tables';
SET test.expected_policies = :'expected_policies';
SET test.expected_indexes = :'expected_indexes';
SET test.expected_min_fk = :'expected_min_fk';

DO $$
DECLARE
    n_tables   int;
    n_rls      int;
    n_policies int;
    n_indexes  int;
    n_fk       int;
    n_funcs    int;
    exp_tables   int := current_setting('test.expected_tables')::int;
    exp_policies int := current_setting('test.expected_policies')::int;
    exp_indexes  int := current_setting('test.expected_indexes')::int;
BEGIN
    SELECT count(*) INTO n_tables
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name <> 'alembic_version'
      AND table_name NOT LIKE 'pg_%';

    IF n_tables <> exp_tables THEN
        RAISE EXCEPTION 'expected % tables, found %', exp_tables, n_tables;
    END IF;

    SELECT count(*) INTO n_rls
    FROM pg_class c
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
    WHERE ns.nspname = 'public' AND c.relkind = 'r'
      AND c.relrowsecurity AND c.relforcerowsecurity;
    IF n_rls <> n_tables THEN
        RAISE EXCEPTION 'RLS not enabled+forced on every table: % of %', n_rls, n_tables;
    END IF;

    SELECT count(*) INTO n_policies FROM pg_policies WHERE schemaname = 'public';
    IF n_policies <> exp_policies THEN
        RAISE EXCEPTION 'expected % policies, found %', exp_policies, n_policies;
    END IF;

    SELECT count(*) INTO n_indexes
    FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix\_%';
    IF n_indexes <> exp_indexes THEN
        RAISE EXCEPTION 'expected % indexes, found %', exp_indexes, n_indexes;
    END IF;

    SELECT count(*) INTO n_funcs
    FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace
    WHERE ns.nspname = 'public'
      AND p.proname IN ('app_current_user_id','app_current_request_id','app_current_execution_id');
    IF n_funcs <> 3 THEN
        RAISE EXCEPTION 'expected 3 session context functions, found %', n_funcs;
    END IF;

    SELECT count(*) INTO n_fk
    FROM information_schema.table_constraints
    WHERE constraint_schema = 'public' AND constraint_type = 'FOREIGN KEY';
    IF n_fk < current_setting('test.expected_min_fk')::int THEN
        RAISE EXCEPTION 'expected at least % FKs, found %', current_setting('test.expected_min_fk')::int, n_fk;
    END IF;

    RAISE NOTICE 'schema verified: % tables, % policies, % indexes, % FKs, % functions',
        n_tables, n_policies, n_indexes, n_fk, n_funcs;
END $$;

-- Behaviour checks for the two-layer knowledge base and the mode/version rule.
DO $$
DECLARE
    cat uuid;
    who uuid;
    ok  boolean;
BEGIN
who := gen_random_uuid();
    -- owner_id now has a real FK to users: every row must point at a real teacher
    INSERT INTO users (id, username, display_name) VALUES (who, 'smoke_user', 'Smoke Test');
    INSERT INTO knowledge_categories (id, scope, owner_id, key, name)
    VALUES (gen_random_uuid(), 'platform', NULL, 'tmp_smoke', 'smoke')
    RETURNING id INTO cat;

    ok := false;
    BEGIN
        INSERT INTO knowledge_sources
            (id, scope, owner_id, category_id, source_type, title, rights_status, distribution_scope, created_by)
        VALUES (gen_random_uuid(), 'platform', who, cat, 'textbook', 'x', 'licensed', 'classroom', who);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'platform source with owner_id was accepted (should be rejected)';
    END IF;

    ok := false;
    BEGIN
        INSERT INTO knowledge_sources
            (id, scope, owner_id, category_id, source_type, title, rights_status, distribution_scope, created_by)
        VALUES (gen_random_uuid(), 'platform', NULL, cat, 'textbook', 'x', 'unverified', 'classroom', who);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'platform source with unverified rights was accepted (should be rejected)';
    END IF;

    ok := false;
    BEGIN
        INSERT INTO material_references (id, owner_id, source_material_id, target_material_id, target_version_id, mode, created_by)
        VALUES (gen_random_uuid(), who, gen_random_uuid(), gen_random_uuid(), NULL, 'pinned', who);
    EXCEPTION WHEN foreign_key_violation THEN ok := true;
                WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'pinned reference without a target version was accepted (should be rejected)';
    END IF;

    RAISE NOTICE 'domain constraints behave as designed';
END $$;
