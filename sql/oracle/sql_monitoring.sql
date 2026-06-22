-- Oracle SQL Monitoring Playbook
-- Currently executing monitored SQL statements
SELECT
    sql_id,
    status,
    ROUND(elapsed_time/1000000, 2)  AS elapsed_sec,
    ROUND(cpu_time/1000000, 2)      AS cpu_sec,
    buffer_gets,
    disk_reads,
    username,
    module,
    LEFT(sql_text, 200)             AS sql_text
FROM v$sql_monitor
WHERE status = 'EXECUTING'
ORDER BY elapsed_time DESC
FETCH FIRST 20 ROWS ONLY
