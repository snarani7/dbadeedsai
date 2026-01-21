SELECT
    ROUND(SUM(space_limit) / 1024 / 1024 / 1024, 2) AS \"Total Size (GB)\",
    ROUND(SUM(space_used) / 1024 / 1024 / 1024, 2) AS \"Used Space (GB)\",
    ROUND((SUM(space_limit) - SUM(space_used)) / 1024 / 1024 / 1024, 2) AS \"Available Space (GB)\"
FROM
    v$recovery_file_dest