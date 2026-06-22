-- Oracle Database Size Playbook
-- Total database size, used and free space
SELECT
    d.name                                                  AS database_name,
    ROUND(SUM(df.bytes)/1024/1024/1024, 2)                AS total_gb,
    ROUND(SUM(df.bytes - NVL(fs.bytes,0))/1024/1024/1024, 2) AS used_gb,
    ROUND(SUM(NVL(fs.bytes,0))/1024/1024/1024, 2)         AS free_gb,
    ROUND(SUM(df.bytes - NVL(fs.bytes,0))*100
          /NULLIF(SUM(df.bytes),0), 1)                     AS pct_used
FROM v$database d
CROSS JOIN v$datafile df
LEFT JOIN (
    SELECT file_id, SUM(bytes) AS bytes
    FROM dba_free_space
    GROUP BY file_id
) fs ON df.file# = fs.file_id
GROUP BY d.name
