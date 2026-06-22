-- Oracle Blocking Sessions Playbook
-- Sessions that are blocking other sessions
SELECT
    s.blocking_session,
    s.sid,
    s.serial#,
    s.username,
    s.wait_class,
    s.event,
    s.seconds_in_wait,
    s.status,
    s.machine,
    s.program
FROM v$session s
WHERE s.blocking_session IS NOT NULL
ORDER BY s.seconds_in_wait DESC
