-- PostgreSQL Replication Status Playbook
-- Shows replication lag and status for streaming replication

SELECT 
    client_addr,
    usename,
    application_name,
    state,
    sync_state,
    CASE 
        WHEN pg_is_in_recovery() THEN 'STANDBY'
        ELSE 'PRIMARY'
    END AS server_role,
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS pending_bytes,
    pg_wal_lsn_diff(sent_lsn, write_lsn) AS write_lag_bytes,
    pg_wal_lsn_diff(write_lsn, flush_lsn) AS flush_lag_bytes,
    pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag_bytes,
    write_lag,
    flush_lag,
    replay_lag,
    backend_start,
    NOW() - backend_start AS connection_duration
FROM 
    pg_stat_replication
ORDER BY 
    application_name;
