-- PostgreSQL Long Running Queries Playbook
-- Identifies queries running for more than 5 minutes

SELECT 
    pid,
    usename AS username,
    application_name,
    client_addr,
    NOW() - query_start AS duration,
    state,
    query
FROM 
    pg_stat_activity
WHERE 
    state = 'active'
    AND query_start < NOW() - INTERVAL '5 minutes'
    AND pid <> pg_backend_pid()
ORDER BY 
    duration DESC;
