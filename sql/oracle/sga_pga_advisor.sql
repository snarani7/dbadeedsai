-- Oracle SGA/PGA Advisor Playbook
-- Current SGA breakdown and PGA advisor recommendation
SELECT 'SGA Component' AS type, name, ROUND(value/1024/1024, 0) AS value_mb
FROM v$sga
UNION ALL
SELECT 'PGA Aggregate' AS type, name, ROUND(value/1024/1024, 0) AS value_mb
FROM v$pgastat
WHERE name IN ('aggregate PGA target parameter','aggregate PGA auto target','total PGA inuse','total PGA allocated')
ORDER BY 1, 2
