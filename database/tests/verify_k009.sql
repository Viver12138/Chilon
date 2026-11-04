-- Structural smoke test for the generated K009 DDL (core variant, without the
-- optional pgvector table). Raises an exception on the first mismatch.
--
-- Run with:  psql -v ON_ERROR_STOP=1 -f database/tests/verify_k009.sql

DO $$
DECLARE
    n_tables   int;
    n_rls      int;
    n_policies int;
    n_indexes  int;
    n_fk       int;
    n_funcs    int;
BEGIN
    SELECT count(*) INTO n_tables
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND (table_name LIKE 'knowledge\_%' OR table_name = 'material_knowledge_citations');

    IF n_tables <> 12 THEN
        RAISE EXCEPTION 'expected 12 K009 tables in the core variant, found %', n_tables;
    END IF;

    -- the optional table must be absent unless generated with --with-optional
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = 'knowledge_question_embeddings') THEN
        RAISE NOTICE 'note: optional embeddings table present';
    END IF;

    -- context functions must exist before any policy references them
    SELECT count(*) INTO n_funcs
    FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace
    WHERE ns.nspname = 'public'
      AND p.proname IN ('app_current_user_id','app_current_request_id','app_current_execution_id');
    IF n_funcs <> 3 THEN
        RAISE EXCEPTION 'expected 3 session context functions, found %', n_funcs;
    END IF;

    -- RLS must be enabled and forced on every table
    SELECT count(*) INTO n_rls
    FROM pg_class c
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
    WHERE ns.nspname = 'public'
      AND c.relkind = 'r'
      AND (c.relname LIKE 'knowledge\_%' OR c.relname = 'material_knowledge_citations')
      AND c.relrowsecurity AND c.relforcerowsecurity;

    IF n_rls <> n_tables THEN
        RAISE EXCEPTION 'RLS not enabled+forced on every table: % of %', n_rls, n_tables;
    END IF;

    SELECT count(*) INTO n_policies
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename LIKE 'knowledge\_%';

    IF n_policies <> 4 THEN
        RAISE EXCEPTION 'expected 4 policies, found %', n_policies;
    END IF;

    SELECT count(*) INTO n_indexes
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname LIKE 'ix\_%'
      AND (tablename LIKE 'knowledge\_%' OR tablename = 'material_knowledge_citations');

    IF n_indexes <> 20 THEN
        RAISE EXCEPTION 'expected 20 indexes, found %', n_indexes;
    END IF;

    -- internal foreign keys only (material_versions is deferred by design)
    SELECT count(*) INTO n_fk
    FROM information_schema.table_constraints
    WHERE constraint_schema = 'public' AND constraint_type = 'FOREIGN KEY';

    IF n_fk < 17 THEN
        RAISE EXCEPTION 'expected at least 17 internal FKs, found %', n_fk;
    END IF;

    -- every row must satisfy the two-layer CHECK
    PERFORM 1 FROM pg_constraint WHERE conname = 'ck_knowledge_sources_scope_owner';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'missing scope/owner constraint on knowledge_sources';
    END IF;

    PERFORM 1 FROM pg_constraint WHERE conname = 'ck_knowledge_sources_platform_rights';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'missing platform rights constraint on knowledge_sources';
    END IF;

    PERFORM 1 FROM pg_constraint WHERE conname = 'uq_knowledge_chunks_parse_identity';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'missing chunk parse identity unique constraint';
    END IF;

    RAISE NOTICE 'K009 DDL verified: % tables, % policies, % indexes, % FKs', n_tables, n_policies, n_indexes, n_fk;
END $$;

-- Behaviour checks: the two-layer constraint must actually reject bad rows.
DO $$
DECLARE
    cat uuid;
    who uuid;
    ok  boolean;
BEGIN
    who := gen_random_uuid();
    INSERT INTO knowledge_categories (id, scope, owner_id, key, name)
    VALUES (gen_random_uuid(), 'platform', NULL, 'tmp_smoke', 'smoke')
    RETURNING id INTO cat;

    ok := false;
    BEGIN
        INSERT INTO knowledge_sources
            (id, scope, owner_id, category_id, source_type, title, rights_status, distribution_scope, created_by)
        VALUES
            (gen_random_uuid(), 'platform', who, cat, 'textbook', 'x', 'licensed', 'classroom', who);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'platform source with owner_id was accepted (should be rejected)';
    END IF;

    ok := false;
    BEGIN
        INSERT INTO knowledge_sources
            (id, scope, owner_id, category_id, source_type, title, rights_status, distribution_scope, created_by)
        VALUES
            (gen_random_uuid(), 'platform', NULL, cat, 'textbook', 'x', 'unverified', 'classroom', who);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'platform source with unverified rights was accepted (should be rejected)';
    END IF;

    RAISE NOTICE 'two-layer and platform-rights constraints behave as designed';
END $$;
