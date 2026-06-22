-- Oracle Unusable Indexes Playbook
-- Indexes in UNUSABLE state that need rebuilding
SELECT
    owner,
    index_name,
    table_name,
    index_type,
    status,
    last_analyzed
FROM dba_indexes
WHERE status = 'UNUSABLE'
ORDER BY owner, table_name
