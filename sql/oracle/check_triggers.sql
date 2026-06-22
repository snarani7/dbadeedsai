-- Oracle Check Triggers Playbook
-- All enabled triggers in the database
SELECT
    owner,
    trigger_name,
    trigger_type,
    triggering_event,
    table_name,
    status,
    action_type
FROM dba_triggers
WHERE status = 'ENABLED'
    AND owner NOT IN ('SYS', 'SYSTEM', 'MDSYS', 'ORDSYS', 'EXFSYS', 'WMSYS', 'XDB')
ORDER BY owner, table_name
FETCH FIRST 100 ROWS ONLY
