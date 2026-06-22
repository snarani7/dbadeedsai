-- Oracle Long Running SQLs Playbook
-- Queries running longer than 5 minutes
SELECT
    s.sid,
    s.serial#,
    s.username,
    s.status,
    s.machine,
    s.program,
    ROUND(s.last_call_et/60, 2) AS runtime_minutes,
    q.sql_text,
    s.blocking_session
FROM
    v$session s,
    v$sql q
WHERE
    s.sql_id = q.sql_id(+)
    AND s.status = 'ACTIVE'
    AND s.username IS NOT NULL
    AND s.last_call_et > 300
ORDER BY
    s.last_call_et DESC
FETCH FIRST 30 ROWS ONLY
