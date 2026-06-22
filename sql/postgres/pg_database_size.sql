-- PostgreSQL Database Size Playbook
-- Shows the size of all databases in the cluster

SELECT 
    datname AS database_name,
    pg_size_pretty(pg_database_size(datname)) AS size,
    pg_database_size(datname) AS size_bytes
FROM 
    pg_database
ORDER BY 
    pg_database_size(datname) DESC;
