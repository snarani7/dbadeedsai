-- PostgreSQL Slow Queries Playbook
-- Shows the slowest queries based on pg_stat_statements
-- Note: Requires pg_stat_statements extension to be enabled

SELECT 
    userid::regrole AS user_name,
    dbid::regclass AS database_name,
    queryid,
    calls,
    ROUND(total_exec_time::numeric, 2) AS total_exec_time_ms,
    ROUND(mean_exec_time::numeric, 2) AS mean_exec_time_ms,
    ROUND(min_exec_time::numeric, 2) AS min_exec_time_ms,
    ROUND(max_exec_time::numeric, 2) AS max_exec_time_ms,
    ROUND(stddev_exec_time::numeric, 2) AS stddev_exec_time_ms,
    rows,
    ROUND(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) AS cache_hit_ratio,
    LEFT(query, 200) AS query_text
FROM 
    pg_stat_statements
ORDER BY 
    total_exec_time DESC
LIMIT 50;
