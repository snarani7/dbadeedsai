WITH
    MAX_PGA AS (
        SELECT ROUND(value/1024/1024,1) AS max_pga
        FROM v\$pgastat
        WHERE name = 'maximum PGA allocated'
    ),
    MGA_CURR AS (
        SELECT ROUND(value/1024/1024,1) AS mga_curr
        FROM v\$pgastat
        WHERE name = 'MGA allocated (under PGA)'
    ),
    MAX_UTIL AS (
        SELECT max_utilization AS max_util
        FROM v\$resource_limit
        WHERE resource_name = 'processes'
    ),
    SGA_TARGET_ADVICE AS (
        SELECT
            sga_size,
            sga_size_factor,
            estd_db_time_factor
        FROM
            v$sga_target_advice
    )
SELECT
    a.max_pga AS \"Max PGA (MB)\",
    b.mga_curr AS \"Current MGA (MB)\",
    c.max_util AS \"Max # of processes\",
    ROUND(((a.max_pga - b.mga_curr) + (c.max_util * 5)) * 1.1, 1) AS \"New PGA_AGGREGATE_LIMIT (MB)\",
    sga.sga_size AS \"SGA Size (MB)\",
    sga.sga_size_factor AS \"SGA Size Factor\",
    sga.estd_db_time_factor AS \"Estimated DB Time Factor\"
FROM
    MAX_PGA a,
    MGA_CURR b,
    MAX_UTIL c,
    SGA_TARGET_ADVICE sga
WHERE 1 = 1
ORDER BY sga.sga_size_factor