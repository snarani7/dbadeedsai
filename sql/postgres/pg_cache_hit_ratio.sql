-- PostgreSQL Cache Hit Ratio Playbook
-- Shows buffer cache hit ratio (should be > 99%)

SELECT 
    'Buffer Cache Hit Ratio' AS metric,
    ROUND(
        100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0),
        2
    ) AS hit_ratio_percent,
    sum(blks_hit) AS cache_hits,
    sum(blks_read) AS disk_reads,
    sum(blks_hit) + sum(blks_read) AS total_reads
FROM 
    pg_stat_database
WHERE 
    datname = current_database()
UNION ALL
SELECT 
    'Index Cache Hit Ratio' AS metric,
    ROUND(
        100.0 * sum(idx_blks_hit) / NULLIF(sum(idx_blks_hit) + sum(idx_blks_read), 0),
        2
    ) AS hit_ratio_percent,
    sum(idx_blks_hit) AS cache_hits,
    sum(idx_blks_read) AS disk_reads,
    sum(idx_blks_hit) + sum(idx_blks_read) AS total_reads
FROM 
    pg_statio_user_indexes;
