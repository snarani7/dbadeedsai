-- PostgreSQL Table Sizes Playbook
-- Shows the size of all tables in the current database

SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS indexes_size,
    pg_total_relation_size(schemaname||'.'||tablename) AS total_size_bytes
FROM 
    pg_tables
WHERE 
    schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY 
    pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 50;
