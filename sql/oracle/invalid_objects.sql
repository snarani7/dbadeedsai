-- Oracle Invalid Objects Playbook
-- All objects with INVALID status
SELECT
    owner,
    object_name,
    object_type,
    status,
    last_ddl_time
FROM dba_objects
WHERE status = 'INVALID'
ORDER BY owner, object_type, object_name
