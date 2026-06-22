-- PostgreSQL Index Usage Playbook
-- Shows index usage statistics and identifies unused indexes

SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan AS index_scans,
    idx_tup_read AS tuples_read,
    idx_tup_fetch AS tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    CASE 
        WHEN idx_scan = 0 THEN 'UNUSED'
        WHEN idx_scan < 100 THEN 'RARELY USED'
        ELSE 'FREQUENTLY USED'
    END AS usage_status
FROM 
    pg_stat_user_indexes
ORDER BY 
    idx_scan ASC,
    pg_relation_size(indexrelid) DESC;
