SELECT
    sl.sid,
    sl.serial#,
    sl.sofar,
    sl.totalwork,
    ROUND((sl.sofar/sl.totalwork)*100, 2) AS percent_complete,
    dp.owner_name,
    dp.state,
    dp.job_mode,
    sl.machine
FROM
    gv$session_longops sl,
    gv$datapump_job dp
WHERE
    sl.opname = dp.job_name
    AND sl.sofar != sl.totalwork
    AND sl.opname LIKE 'Data Pump%'