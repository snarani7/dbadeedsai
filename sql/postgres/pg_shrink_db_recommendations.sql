-- ============================================================
-- PostgreSQL Shrink DB Recommendations Playbook
-- Identifies bloat, wasted space, and actionable commands
-- to reclaim disk space across tables, indexes, and TOAST.
--
-- Categories returned:
--   TABLE BLOAT     — dead tuples, VACUUM FULL / pg_repack candidates
--   INDEX BLOAT     — oversized or unused indexes safe to rebuild/drop
--   NEVER VACUUMED  — tables with no autovacuum history
--   INDEX REDUNDANT — duplicate / redundant indexes to drop
--   TOAST BLOAT     — large TOAST segments from deleted rows
--   DB SUMMARY      — overall database bloat estimate
-- ============================================================

WITH

-- ── 1. Table bloat via dead-tuple ratio ───────────────────────────────────────
table_bloat AS (
    SELECT
        s.schemaname,
        s.relname                                                   AS table_name,
        c.reltuples::bigint                                         AS estimated_rows,
        s.n_live_tup                                                AS live_tuples,
        s.n_dead_tup                                                AS dead_tuples,
        pg_total_relation_size(c.oid)                               AS total_bytes,
        pg_relation_size(c.oid)                                     AS table_bytes,
        ROUND(
            100.0 * s.n_dead_tup
            / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 1
        )                                                           AS dead_pct,
        s.last_autovacuum,
        s.last_vacuum,
        s.last_autoanalyze
    FROM   pg_stat_user_tables s
    JOIN   pg_class             c ON c.relname = s.relname
                                 AND c.relnamespace = (
                                       SELECT oid FROM pg_namespace
                                       WHERE  nspname = s.schemaname)
    WHERE  s.schemaname NOT IN ('pg_catalog','information_schema','pg_toast')
),

-- ── 2. Index sizes and scan counts ───────────────────────────────────────────
index_stats AS (
    SELECT
        ix.schemaname,
        ix.relname                                AS table_name,
        ix.indexrelname                           AS index_name,
        ix.idx_scan                               AS scans,
        pg_relation_size(ix.indexrelid)           AS index_bytes,
        pg_get_indexdef(ix.indexrelid)            AS index_def,
        i.indisprimary                            AS is_primary,
        i.indisunique                             AS is_unique
    FROM   pg_stat_user_indexes ix
    JOIN   pg_index              i  ON i.indexrelid = ix.indexrelid
    WHERE  ix.schemaname NOT IN ('pg_catalog','information_schema')
),

-- ── 3. TOAST table sizes ──────────────────────────────────────────────────────
toast_sizes AS (
    SELECT
        n.nspname                                 AS schemaname,
        c.relname                                 AS table_name,
        pg_relation_size(t.oid)                   AS toast_bytes,
        t.relname                                 AS toast_relname
    FROM   pg_class   c
    JOIN   pg_class   t  ON t.oid = c.reltoastrelid
    JOIN   pg_namespace n ON n.oid = c.relnamespace
    WHERE  c.reltoastrelid <> 0
      AND  n.nspname NOT IN ('pg_catalog','information_schema')
      AND  pg_relation_size(t.oid) > 10 * 1024 * 1024   -- >10 MB TOAST only
),

-- ── 4. Duplicate / redundant indexes (same leading column + table) ────────────
dup_indexes AS (
    SELECT
        ix1.schemaname,
        ix1.relname                               AS table_name,
        ix1.indexrelname                          AS index_1,
        ix2.indexrelname                          AS index_2,
        pg_relation_size(ix1.indexrelid)          AS idx1_bytes,
        pg_relation_size(ix2.indexrelid)          AS idx2_bytes,
        ix1.idx_scan                              AS idx1_scans,
        ix2.idx_scan                              AS idx2_scans
    FROM   pg_stat_user_indexes ix1
    JOIN   pg_stat_user_indexes ix2
           ON  ix1.relid       = ix2.relid
           AND ix1.indexrelid  < ix2.indexrelid
    JOIN   pg_index i1 ON i1.indexrelid = ix1.indexrelid
    JOIN   pg_index i2 ON i2.indexrelid = ix2.indexrelid
    WHERE  ix1.schemaname NOT IN ('pg_catalog','information_schema')
      AND  NOT i1.indisprimary
      AND  NOT i2.indisprimary
      -- Same set of indexed columns
      AND  i1.indkey::text = i2.indkey::text
      AND  i1.indrelid      = i2.indrelid
),

-- ── Assemble all recommendations ─────────────────────────────────────────────
recommendations AS (

    -- ── A. High dead-tuple bloat (>20% dead, table >5 MB) ───────────────────
    SELECT
        CASE
            WHEN dead_pct >= 50 THEN '🔴 HIGH'
            WHEN dead_pct >= 20 THEN '🟡 MEDIUM'
            ELSE                     '🟢 LOW'
        END                                       AS priority,
        'TABLE BLOAT'                             AS category,
        schemaname                                AS schema_name,
        table_name                                AS object_name,
        pg_size_pretty(total_bytes)               AS current_size,
        pg_size_pretty(
            GREATEST(table_bytes * dead_pct / 100, 0)::bigint
        )                                         AS est_reclaimable,
        dead_pct || '% dead tuples ('
            || dead_tuples || ' rows)'            AS detail,
        CASE
            WHEN dead_pct >= 50
                 THEN 'VACUUM FULL ANALYZE ' || schemaname || '.' || table_name
                      || ';  -- OR use pg_repack for zero-downtime'
            ELSE      'VACUUM ANALYZE ' || schemaname || '.' || table_name || ';'
        END                                       AS recommended_command,
        total_bytes                               AS sort_bytes
    FROM   table_bloat
    WHERE  dead_pct >= 20
      AND  total_bytes > 5 * 1024 * 1024

    UNION ALL

    -- ── B. Never vacuumed tables (>1 MB, no autovacuum ever) ────────────────
    SELECT
        '🟡 MEDIUM',
        'NEVER VACUUMED',
        schemaname,
        table_name,
        pg_size_pretty(total_bytes),
        '—',
        'No autovacuum or manual VACUUM recorded',
        'VACUUM ANALYZE ' || schemaname || '.' || table_name || ';',
        total_bytes
    FROM   table_bloat
    WHERE  last_autovacuum IS NULL
      AND  last_vacuum     IS NULL
      AND  total_bytes > 1024 * 1024   -- >1 MB

    UNION ALL

    -- ── C. Bloated unused indexes (0 scans, >1 MB, non-PK/UK) ──────────────
    SELECT
        '🟡 MEDIUM',
        'INDEX BLOAT – UNUSED',
        schemaname,
        index_name,
        pg_size_pretty(index_bytes),
        pg_size_pretty(index_bytes),
        '0 scans since last stats reset — likely unused',
        'DROP INDEX CONCURRENTLY ' || schemaname || '.' || index_name
            || ';  -- verify in pg_stat_user_indexes first',
        index_bytes
    FROM   index_stats
    WHERE  scans     = 0
      AND  is_primary = false
      AND  is_unique  = false
      AND  index_bytes > 1024 * 1024

    UNION ALL

    -- ── D. Very large indexes with low scan rate (>50 MB, <100 scans) ───────
    SELECT
        '🟡 MEDIUM',
        'INDEX BLOAT – LOW USAGE',
        schemaname,
        index_name,
        pg_size_pretty(index_bytes),
        '—',
        scans || ' total scans — index may be over-sized for usage',
        'REINDEX INDEX CONCURRENTLY ' || schemaname || '.' || index_name
            || ';  -- reclaims internal page bloat',
        index_bytes
    FROM   index_stats
    WHERE  scans        < 100
      AND  is_primary   = false
      AND  index_bytes  > 50 * 1024 * 1024

    UNION ALL

    -- ── E. Redundant / duplicate indexes ────────────────────────────────────
    SELECT
        '🟡 MEDIUM',
        'INDEX REDUNDANT',
        schemaname,
        index_2 || ' (dup of ' || index_1 || ')',
        pg_size_pretty(idx2_bytes),
        pg_size_pretty(idx2_bytes),
        'Same columns as ' || index_1
            || ' — idx1 scans=' || idx1_scans
            || ', idx2 scans=' || idx2_scans,
        'DROP INDEX CONCURRENTLY ' || schemaname || '.' || index_2
            || ';  -- keep ' || index_1 || ' (higher scan count)',
        idx2_bytes
    FROM   dup_indexes

    UNION ALL

    -- ── F. Large TOAST segments ──────────────────────────────────────────────
    SELECT
        '🟢 LOW',
        'TOAST BLOAT',
        schemaname,
        table_name || ' (TOAST: ' || toast_relname || ')',
        pg_size_pretty(toast_bytes),
        '—',
        'Large TOAST segment — likely from deleted/updated text or bytea columns',
        'VACUUM FULL ' || schemaname || '.' || table_name
            || ';  -- reclaims TOAST space (locks table)',
        toast_bytes
    FROM   toast_sizes
    WHERE  toast_bytes > 50 * 1024 * 1024

)

SELECT
    priority                                      AS "Priority",
    category                                      AS "Category",
    schema_name                                   AS "Schema",
    object_name                                   AS "Object",
    current_size                                  AS "Current Size",
    est_reclaimable                               AS "Est. Reclaimable",
    detail                                        AS "Detail",
    recommended_command                           AS "Recommended Command"
FROM   recommendations
ORDER BY
    CASE priority
        WHEN '🔴 HIGH'   THEN 1
        WHEN '🟡 MEDIUM' THEN 2
        ELSE                  3
    END,
    sort_bytes DESC;
