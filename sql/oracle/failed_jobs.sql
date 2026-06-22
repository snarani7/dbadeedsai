-- Oracle Failed Jobs Playbook
-- Scheduler jobs that have failed recently
SELECT
    log_id,
    job_name,
    status,
    error#,
    actual_start_date,
    run_duration,
    additional_info
FROM dba_scheduler_job_run_details
WHERE status = 'FAILED'
ORDER BY actual_start_date DESC
FETCH FIRST 50 ROWS ONLY
