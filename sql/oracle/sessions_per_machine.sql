-- Oracle Sessions Per Machine Playbook
-- Connection count by client machine
SELECT
    machine,
    COUNT(*)                                              AS total_sessions,
    SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END)  AS active_sessions,
    SUM(CASE WHEN status = 'INACTIVE' THEN 1 ELSE 0 END) AS inactive_sessions,
    COUNT(DISTINCT username)                              AS distinct_users
FROM v$session
WHERE type = 'USER'
GROUP BY machine
ORDER BY total_sessions DESC
