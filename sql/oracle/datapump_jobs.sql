-- Oracle Datapump Jobs Playbook
-- Active Data Pump export/import jobs
SELECT
    owner_name,
    job_name,
    operation,
    job_mode,
    state,
    attached_sessions,
    degree,
    datapump_sessions
FROM dba_datapump_jobs
WHERE state != 'NOT RUNNING'
ORDER BY job_name
