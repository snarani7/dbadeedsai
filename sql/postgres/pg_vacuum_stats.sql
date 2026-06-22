-- PostgreSQL Vacuum Statistics Playbook
-- Shows when tables were last vacuumed and analyzed

SELECT 
    schemaname,
    relname AS table_name,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    vacuum_count,
    autovacuum_count,
    analyze_count,
    autoanalyze_count,
    n_tup_ins AS inserts,
    n_tup_upd AS updates,
    n_tup_del AS deletes,
    n_live_tup AS live_tuples,
    n_dead_tup AS dead_tuples,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tuple_percent
FROM 
    pg_stat_user_tables
ORDER BY 
    n_dead_tup DESC,
    last_autovacuum NULLS FIRST
LIMIT 50;
