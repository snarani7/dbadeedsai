-- PostgreSQL Locks Overview Playbook
-- Shows current locks in the database

SELECT 
    pl.pid,
    pa.usename,
    pa.application_name,
    pl.locktype,
    pl.mode,
    pl.granted,
    CASE 
        WHEN pl.relation IS NOT NULL THEN 
            pc.relname
        ELSE NULL
    END AS relation_name,
    pa.query_start,
    NOW() - pa.query_start AS query_duration,
    LEFT(pa.query, 100) AS query_text
FROM 
    pg_locks pl
    LEFT JOIN pg_stat_activity pa ON pl.pid = pa.pid
    LEFT JOIN pg_class pc ON pl.relation = pc.oid
WHERE 
    pl.pid <> pg_backend_pid()
ORDER BY 
    query_duration DESC NULLS LAST,
    pl.granted,
    pl.pid;
