SELECT
    d.tablespace_name,
    d.status,
    ROUND(MAX(d.bytes) / (1024 * 1024 * 1024), 2) AS total_gb,
    ROUND(SUM(DECODE(f.free_gb, NULL, 0, f.free_gb)), 2) AS free_gb,
    ROUND(((MAX(d.bytes) - SUM(DECODE(f.free_gb, NULL, 0, f.free_gb))) / MAX(d.bytes)) * 100, 2) AS percent_used
FROM
    (SELECT tablespace_name, status, SUM(bytes) bytes FROM dba_data_files GROUP BY tablespace_name, status) d,
    (SELECT tablespace_name, ROUND(SUM(bytes) / (1024 * 1024 * 1024), 2) AS free_gb FROM dba_free_space GROUP BY tablespace_name) f
WHERE
    d.tablespace_name = f.tablespace_name(+)
    AND d.status = 'ONLINE'
HAVING
    ROUND(((MAX(d.bytes) - SUM(DECODE(f.free_gb, NULL, 0, f.free_gb))) / MAX(d.bytes)) * 100, 2) > 85
GROUP BY
    d.tablespace_name, d.status
ORDER BY
    percent_used DESC