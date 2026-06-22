"""
SQL Safety Validator Module
Prevents dangerous SQL operations (DROP, TRUNCATE, DELETE, UPDATE, INSERT, etc.)
while allowing all legitimate DBA monitoring queries.
"""

import re
from typing import Tuple


class SQLSafetyValidator:
    """
    Validates SQL queries to prevent dangerous operations.
    Read-only monitoring queries are always allowed.
    """

    # DDL / DML keywords that must NEVER appear as the leading verb of a statement
    DANGEROUS_LEADING_KEYWORDS = [
        'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'DELETE', 'UPDATE',
        'INSERT', 'MERGE', 'GRANT', 'REVOKE', 'REPLACE',
        'RENAME', 'COMMENT', 'FLASHBACK', 'PURGE',
    ]

    # These keywords are also dangerous even deep inside a query (e.g. subqueries)
    DANGEROUS_INLINE_KEYWORDS = ['DROP', 'TRUNCATE']

    # Dangerous stored-procedure / system-function patterns.
    # Each entry is a regex pattern applied with re.search on the upper-cased SQL.
    # Use word boundaries (\b) or anchored prefixes so we don't false-positive on
    # column/table names that happen to contain a substring.
    DANGEROUS_FUNCTION_PATTERNS = [
        r'\bDBMS_\w+(?:\.\w+)?\s*\(',  # Oracle DBMS packages: DBMS_SCHEDULER(, DBMS_OUTPUT.PUT_LINE( …
        r'\bUTL_\w+(?:\.\w+)?\s*\(',   # Oracle UTL packages
        r'\bCTX_\w+(?:\.\w+)?\s*\(',   # Oracle Text packages
        r'\bMDSYS\.',                # Oracle Spatial
        r'\bEXEC(?:UTE)?\s+\w',     # EXEC proc or EXECUTE proc  (NOT exec_time / execution_plan)
        r'\bCALL\s+\w',             # CALL procedure(
        r'\bBEGIN\s+(?!ISOLATION|TRANSACTION|WORK|DEFERRED|IMMEDIATE|EXCLUSIVE)\w',  # BEGIN pl/pgsql block (not BEGIN TRANSACTION/ISOLATION)
        r'\bDECLARE\s+\w',          # DECLARE variable
        r'\blo_\w+\s*\(',           # PostgreSQL large-object funcs: lo_create(, lo_import(
        r'\bpg_terminate_backend\s*\(',
        r'\bpg_cancel_backend\s*\(',
        r'\bpg_reload_conf\s*\(',
        r'\bpg_read_file\s*\(',
        r'\bpg_ls_dir\s*\(',
        r'\bcopy\s+\w+\s+(?:to|from)\s+', # COPY … TO/FROM filesystem
    ]

    @staticmethod
    def _clean(sql: str) -> str:
        """Strip comments and normalise whitespace."""
        s = re.sub(r'--[^\n]*', ' ', sql)
        s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL)
        return s.strip().upper()

    @staticmethod
    def is_safe_query(sql: str, allow_select_only: bool = True) -> Tuple[bool, str]:
        """
        Check if SQL query is safe to execute.

        Args:
            sql: SQL query to validate
            allow_select_only: If True, only read-only queries are allowed

        Returns:
            (is_safe, message)
        """
        if not sql or not sql.strip():
            return False, "Empty query"

        sql_upper = SQLSafetyValidator._clean(sql)

        # ── 1. Block dangerous LEADING keywords ──────────────────────────────
        for kw in SQLSafetyValidator.DANGEROUS_LEADING_KEYWORDS:
            if re.match(r'^\s*' + kw + r'\b', sql_upper):
                return False, "❌ BLOCKED: {} operations are not allowed".format(kw)

        # ── 2. Block dangerous keywords anywhere inside the query ─────────────
        for kw in SQLSafetyValidator.DANGEROUS_INLINE_KEYWORDS:
            if re.search(r'\b' + kw + r'\b', sql_upper):
                return False, "❌ BLOCKED: {} detected inside query".format(kw)

        # ── 3. Block dangerous function/procedure patterns ────────────────────
        for pattern in SQLSafetyValidator.DANGEROUS_FUNCTION_PATTERNS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return False, "❌ BLOCKED: dangerous operation detected — {}".format(pattern)

        # ── 4. Read-only gate ─────────────────────────────────────────────────
        if allow_select_only:
            ok_starts = ('SELECT', 'WITH', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN', 'TABLE')
            if not any(sql_upper.startswith(kw) for kw in ok_starts):
                return False, "❌ BLOCKED: Only SELECT / SHOW / DESCRIBE / EXPLAIN queries are allowed"
            # WITH must contain a SELECT
            if sql_upper.startswith('WITH') and 'SELECT' not in sql_upper:
                return False, "❌ BLOCKED: WITH clause must include a SELECT"

        # ── 5. No stacked statements ──────────────────────────────────────────
        # Use comment-stripped sql_upper so semicolons inside -- comments or
        # /* */ blocks don't false-positive (e.g. Gemini writes inline comments
        # like "-- top 10 queries; ordered by cost" which contain a semicolon)
        sql_trimmed = sql_upper.rstrip(';').rstrip()
        if ';' in sql_trimmed:
            return False, "❌ BLOCKED: Multiple statements are not allowed (SQL injection protection)"

        return True, "✓ Query is safe"

    @staticmethod
    def sanitize_for_display(sql: str, max_length: int = 200) -> str:
        if not sql:
            return ""
        if len(sql) > max_length:
            sql = sql[:max_length] + "..."
        sql = re.sub(r'password\s*=\s*[\'"][^\'"]*[\'"]', 'password=***', sql, flags=re.IGNORECASE)
        sql = re.sub(r'pwd\s*=\s*[\'"][^\'"]*[\'"]', 'pwd=***', sql, flags=re.IGNORECASE)
        return sql

    @staticmethod
    def get_safe_query_help() -> str:
        return """
**🛡️ SQL Safety Guardrails Active**

**Allowed Operations:**
✅ SELECT — Query and analyse data
✅ WITH (CTE) — Common Table Expressions
✅ SHOW — Show database objects
✅ DESCRIBE / DESC — Describe table structure
✅ EXPLAIN — Explain query execution plan

**PostgreSQL Monitoring Views (fully supported):**
✅ pg_stat_statements, pg_stat_activity, pg_stat_user_tables
✅ pg_locks, pg_stat_bgwriter, pg_stat_replication
✅ pg_stat_user_indexes, pg_statio_user_tables, pg_database

**Oracle Monitoring Views (fully supported):**
✅ v$session, v$sql, v$active_session_history, v$sysstat
✅ dba_segments, dba_objects, v$lock, v$latch

**Blocked Operations:**
❌ CREATE / ALTER / DROP — Schema changes
❌ DELETE / TRUNCATE — Row removal
❌ UPDATE / INSERT / MERGE — Data modification
❌ GRANT / REVOKE — Permission changes
❌ EXEC / CALL / BEGIN / DECLARE — Procedural execution
❌ DBMS_ / UTL_ / lo_ — Dangerous packages & functions
❌ pg_terminate_backend / pg_cancel_backend — Session control
❌ COPY TO/FROM filesystem — File access
❌ Multiple statements — SQL injection protection

**Need to modify data?** Use a dedicated SQL client with proper authorisation.
"""


class QueryTypeDetector:
    @staticmethod
    def get_query_type(sql: str) -> str:
        if not sql:
            return "UNKNOWN"
        s = re.sub(r'--[^\n]*', ' ', sql)
        s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL).strip().upper()
        for qtype, starts in [
            ("SELECT",   ("SELECT", "WITH")),
            ("SHOW",     ("SHOW",)),
            ("DESCRIBE", ("DESCRIBE", "DESC")),
            ("EXPLAIN",  ("EXPLAIN",)),
            ("INSERT",   ("INSERT",)),
            ("UPDATE",   ("UPDATE",)),
            ("DELETE",   ("DELETE",)),
            ("CREATE",   ("CREATE",)),
            ("ALTER",    ("ALTER",)),
            ("DROP",     ("DROP",)),
            ("TRUNCATE", ("TRUNCATE",)),
            ("DCL",      ("GRANT", "REVOKE")),
        ]:
            if any(s.startswith(k) for k in starts):
                return qtype
        return "UNKNOWN"

    @staticmethod
    def is_read_only(sql: str) -> bool:
        return QueryTypeDetector.get_query_type(sql) in ('SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN')


# ── Convenience functions ──────────────────────────────────────────────────────

def validate_sql(sql: str, allow_select_only: bool = True) -> Tuple[bool, str]:
    """Validate SQL query for safety."""
    return SQLSafetyValidator.is_safe_query(sql, allow_select_only)


def is_safe_sql(sql: str) -> bool:
    """Return True only if the query passes all safety checks."""
    safe, _ = SQLSafetyValidator.is_safe_query(sql)
    return safe


def get_safety_help() -> str:
    """Return human-readable safety guidance."""
    return SQLSafetyValidator.get_safe_query_help()