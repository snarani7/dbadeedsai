-- Oracle Application Long Running Queries Playbook
-- Long running queries by application module
SELECT
    s.module,
    s.action,
    s.username,
    s.machine,
    ROUND(s.last_call_et/60, 2) AS runtime_minutes,
    q.sql_text,
    q.executions,
    ROUND(q.elapsed_time/1000000/NULLIF(q.executions,0), 3) AS avg_elapsed_sec
FROM v$session s
JOIN v$sql q ON s.sql_id = q.sql_id
WHERE s.status = 'ACTIVE'
    AND s.module IS NOT NULL
    AND s.last_call_et > 180
ORDER BY s.last_call_et DESC
FETCH FIRST 20 ROWS ONLY
