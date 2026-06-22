-- PostgreSQL Active Connections Playbook
-- Shows all active database connections and their states

SELECT 
    pid,
    usename AS username,
    application_name,
    client_addr,
    client_port,
    backend_start,
    state,
    state_change,
    query_start,
    CASE 
        WHEN state = 'active' THEN 
            EXTRACT(EPOCH FROM (NOW() - query_start))
        ELSE NULL 
    END AS active_seconds,
    LEFT(query, 100) AS current_query
FROM 
    pg_stat_activity
WHERE 
    pid <> pg_backend_pid()  -- Exclude current connection
ORDER BY 
    backend_start DESC;
