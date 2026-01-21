SELECT
        sql_fulltext
    FROM
        gv$sql
    WHERE
        inst_id = $blocker_inst_id