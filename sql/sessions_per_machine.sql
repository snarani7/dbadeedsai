SELECT
    inst_id,
    machine AS machine_name,
    SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END) AS active_sessions,
    SUM(CASE WHEN status = 'INACTIVE' THEN 1 ELSE 0 END) AS inactive_sessions,
    COUNT(sid) AS total_sessions
FROM
    gv$session
GROUP BY
    inst_id, machine
ORDER BY
    inst_id, total_sessions DESC