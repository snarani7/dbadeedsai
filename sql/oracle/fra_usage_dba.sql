-- Oracle FRA (Flash Recovery Area) Usage Playbook
SELECT
    ROUND(space_limit/1024/1024/1024, 2)       AS limit_gb,
    ROUND(space_used/1024/1024/1024, 2)        AS used_gb,
    ROUND(space_reclaimable/1024/1024/1024, 2) AS reclaimable_gb,
    number_of_files,
    ROUND(space_used*100/NULLIF(space_limit,0), 1) AS pct_used
FROM v$recovery_file_dest
