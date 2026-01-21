SELECT
    x.inst_id,
    x.sid,
    x.username,
    x.sql_id,
    sqlarea.DISK_READS,
    sqlarea.BUFFER_GETS,
    x.event,
    x.status,
    x.BLOCKING_SESSION,
    x.machine,
    x.program,
    x.LAST_CALL_ET,
    ltrim(to_char(floor(x.LAST_CALL_ET/3600), '09')) || ':'
    || ltrim(to_char(floor(mod(x.LAST_CALL_ET, 3600)/60), '09')) || ':'
    || ltrim(to_char(mod(x.LAST_CALL_ET, 60), '09')) AS RUNNING_SINCE
FROM
    gv$sqlarea sqlarea,
    gv$session x
WHERE
    x.sql_hash_value = sqlarea.hash_value
    AND x.sql_address = sqlarea.address
    AND x.inst_id = sqlarea.inst_id
    AND x.status = 'ACTIVE'
    AND x.username IS NOT NULL
ORDER BY
    RUNNING_SINCE DESC