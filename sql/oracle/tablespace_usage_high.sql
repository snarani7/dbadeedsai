-- Oracle Tablespace Usage High Playbook
-- Tablespaces with usage above 80%
SELECT
    tablespace_name,
    ROUND(used_space * 8192/1024/1024/1024, 2)       AS used_gb,
    ROUND(tablespace_size * 8192/1024/1024/1024, 2)  AS total_gb,
    ROUND(used_percent, 1)                            AS pct_used,
    CASE
        WHEN used_percent >= 95 THEN 'CRITICAL'
        WHEN used_percent >= 90 THEN 'WARNING'
        ELSE 'HIGH'
    END AS severity
FROM dba_tablespace_usage_metrics
WHERE used_percent > 80
ORDER BY used_percent DESC
