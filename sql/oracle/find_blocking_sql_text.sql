-- Oracle Find Blocking SQL Text Playbook
-- Shows blocking chain with SQL text
SELECT
    s.sid,
    s.blocking_session,
    s.seconds_in_wait,
    s.username,
    s.machine,
    q.sql_text
FROM v$session s
JOIN v$sql q ON s.sql_id = q.sql_id
WHERE s.blocking_session IS NOT NULL
ORDER BY s.seconds_in_wait DESC
FETCH FIRST 20 ROWS ONLY
