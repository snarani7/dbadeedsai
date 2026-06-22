-- PostgreSQL Database Activity Playbook
-- Shows overall database activity statistics

SELECT 
    datname AS database_name,
    numbackends AS active_connections,
    xact_commit AS transactions_committed,
    xact_rollback AS transactions_rolled_back,
    ROUND(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS rollback_ratio_percent,
    blks_read AS blocks_read_from_disk,
    blks_hit AS blocks_hit_in_cache,
    ROUND(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS cache_hit_ratio_percent,
    tup_returned AS tuples_returned,
    tup_fetched AS tuples_fetched,
    tup_inserted AS tuples_inserted,
    tup_updated AS tuples_updated,
    tup_deleted AS tuples_deleted,
    conflicts AS conflicts,
    temp_files AS temp_files_created,
    pg_size_pretty(temp_bytes) AS temp_bytes_written,
    deadlocks,
    stats_reset
FROM 
    pg_stat_database
WHERE 
    datname = current_database();
