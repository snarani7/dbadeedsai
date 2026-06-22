"""
agent_executor_tools.py — LangChain DB tools for AI Agents & AI Assistant.

Mirrors the original Streamlit app's:
  - run_oracle_query_for_agent()
  - run_postgres_query_for_agent()
  - tools[] list (OracleQueryAgent, PostgresQueryAgent)
  - AgentManager, AgentTemplates, AgentConfig, AgentExecutor
  - AGENT_PLAYBOOKS

All logic is identical to Streamlit: same SQL cleaning, same PII redaction,
same 100-row cap, same error messages, same tool descriptions.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from langchain.tools import Tool


# ── Enums ─────────────────────────────────────────────────────────────────────

class AgentType(Enum):
    PERFORMANCE_MONITOR = "performance_monitor"
    TROUBLESHOOTER      = "troubleshooter"
    QUERY_OPTIMIZER     = "query_optimizer"
    SECURITY_AUDITOR    = "security_auditor"
    CAPACITY_PLANNER    = "capacity_planner"
    BACKUP_MONITOR      = "backup_monitor"
    CUSTOM              = "custom"


class DatabaseType(Enum):
    ORACLE     = "oracle"
    POSTGRESQL = "postgresql"


# ── AgentConfig dataclass ─────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    name: str
    agent_type: AgentType
    database_type: DatabaseType
    description: str
    system_prompt: str
    tools: list
    temperature: float = 0.0
    model: str = "gpt-4o"
    max_iterations: int = 10
    created_at: str = None
    updated_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["agent_type"]    = self.agent_type.value
        data["database_type"] = self.database_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        d = dict(data)
        d["agent_type"]    = AgentType(d["agent_type"])
        d["database_type"] = DatabaseType(d["database_type"])
        return cls(**d)


# ── AgentTemplates (all 16 — exact copy of Streamlit agent_manager.py) ────────

class AgentTemplates:

    ORACLE_PERFORMANCE_MONITOR = AgentConfig(
        name="Oracle Performance Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.ORACLE,
        description="Monitors Oracle database performance metrics, identifies bottlenecks, and provides optimization recommendations.",
        system_prompt="""You are an expert Oracle DBA specializing in performance monitoring.

Your responsibilities:
- Monitor database performance metrics (CPU, memory, I/O)
- Identify slow-running queries and suggest optimizations
- Analyze AWR/ASH reports
- Check for blocking sessions and locks
- Monitor tablespace usage and alert on capacity issues
- Review execution plans and suggest index improvements

Always provide:
1. Clear diagnosis of performance issues
2. Specific SQL or configuration recommendations
3. Expected impact of changes
4. Risk assessment for proposed changes

Use Oracle-specific tools and queries to gather performance data.""",
        tools=["OracleQueryAgent"], temperature=0.0)

    POSTGRESQL_PERFORMANCE_MONITOR = AgentConfig(
        name="PostgreSQL Performance Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Monitors PostgreSQL database performance, analyzes query execution, and provides tuning recommendations.",
        system_prompt="""You are an expert PostgreSQL DBA specializing in performance monitoring.

Your responsibilities:
- Monitor database performance using pg_stat_* views
- Identify slow queries using pg_stat_statements
- Analyze EXPLAIN plans and suggest optimizations
- Check for blocking queries and lock contention
- Monitor cache hit ratios and suggest buffer pool adjustments
- Review vacuum and analyze statistics
- Identify missing or unused indexes

Always provide:
1. Clear diagnosis of performance issues
2. Specific SQL or postgresql.conf recommendations
3. Expected impact of changes
4. Risk assessment for proposed changes

Use PostgreSQL-specific system catalogs and statistics views.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    ORACLE_TROUBLESHOOTER = AgentConfig(
        name="Oracle Troubleshooter",
        agent_type=AgentType.TROUBLESHOOTER,
        database_type=DatabaseType.ORACLE,
        description="Diagnoses and resolves Oracle database issues, errors, and incidents.",
        system_prompt="""You are an expert Oracle DBA specializing in troubleshooting.

Your responsibilities:
- Diagnose database errors and exceptions
- Investigate connection issues
- Resolve tablespace and storage problems
- Fix invalid objects and broken dependencies
- Troubleshoot backup and recovery issues
- Address security and permission problems

Approach:
1. Gather relevant error messages and logs
2. Check alert.log and trace files
3. Query DBA_* views for diagnostic information
4. Provide step-by-step resolution plan
5. Include rollback procedures if applicable

Always explain root causes and preventive measures.""",
        tools=["OracleQueryAgent"], temperature=0.1)

    POSTGRESQL_TROUBLESHOOTER = AgentConfig(
        name="PostgreSQL Troubleshooter",
        agent_type=AgentType.TROUBLESHOOTER,
        database_type=DatabaseType.POSTGRESQL,
        description="Diagnoses and resolves PostgreSQL database issues, errors, and incidents.",
        system_prompt="""You are an expert PostgreSQL DBA specializing in troubleshooting.

Your responsibilities:
- Diagnose database errors and exceptions
- Investigate connection issues (max_connections, idle connections)
- Resolve disk space and bloat problems
- Fix replication lag and streaming issues
- Troubleshoot vacuum and autovacuum problems
- Address permission and authentication issues

Approach:
1. Check PostgreSQL logs for errors
2. Query system catalogs for diagnostic information
3. Use pg_stat_* views to understand state
4. Provide step-by-step resolution plan
5. Include rollback procedures if applicable

Always explain root causes and preventive measures.""",
        tools=["PostgresQueryAgent"], temperature=0.1)

    ORACLE_QUERY_OPTIMIZER = AgentConfig(
        name="Oracle Query Optimizer",
        agent_type=AgentType.QUERY_OPTIMIZER,
        database_type=DatabaseType.ORACLE,
        description="Analyzes and optimizes SQL queries for Oracle databases.",
        system_prompt="""You are an expert Oracle SQL tuning specialist.

Your responsibilities:
- Analyze execution plans using EXPLAIN PLAN
- Identify missing or inefficient indexes
- Rewrite queries for better performance
- Suggest optimizer hints when appropriate
- Review statistics and recommend gathering
- Identify Cartesian joins and inefficient operations

When optimizing:
1. Always show the original query
2. Explain the performance issue
3. Provide optimized version with explanation
4. Show expected performance improvement
5. Recommend indexes if needed — provide the CREATE INDEX script as a RECOMMENDATION for the DBA
6. Suggest statistics updates if applicable

⚠️  IMPORTANT — RECOMMENDATION MODE ONLY:
- You operate in READ-ONLY mode. Do NOT attempt to CREATE, ALTER, or DROP anything.
- Use EXPLAIN PLAN and query v$sql, v$sql_plan, dba_indexes etc. to gather data.
- Present all DDL changes (CREATE INDEX, GATHER STATS, etc.) as recommendation scripts
  that the DBA will review and execute manually.
- Example output format: "Recommendation: Run the following script → CREATE INDEX ..."

Use bind variables and avoid literals in production queries.""",
        tools=["OracleQueryAgent"], temperature=0.2)

    POSTGRESQL_QUERY_OPTIMIZER = AgentConfig(
        name="PostgreSQL Query Optimizer",
        agent_type=AgentType.QUERY_OPTIMIZER,
        database_type=DatabaseType.POSTGRESQL,
        description="Analyzes and optimizes SQL queries for PostgreSQL databases.",
        system_prompt="""You are an expert PostgreSQL SQL tuning specialist.

Your responsibilities:
- Analyze execution plans using EXPLAIN ANALYZE
- Identify missing or inefficient indexes
- Rewrite queries for better performance
- Optimize JOIN operations and subqueries
- Review table statistics and suggest ANALYZE
- Identify sequential scans that should use indexes

When optimizing:
1. Always show the original query
2. Explain the performance issue using EXPLAIN output
3. Provide optimized version with explanation
4. Show expected performance improvement
5. Recommend indexes (B-tree, GiST, GIN, etc.) — provide the CREATE INDEX script as a RECOMMENDATION for the DBA
6. Suggest work_mem or other parameter adjustments

⚠️  IMPORTANT — RECOMMENDATION MODE ONLY:
- You operate in READ-ONLY mode. Do NOT attempt to CREATE INDEX, ALTER TABLE, or any DDL.
- Use EXPLAIN ANALYZE (within a transaction if needed) and query pg_stat_*, pg_indexes,
  pg_stats etc. to gather data.
- Present all DDL changes (CREATE INDEX, ALTER TABLE, VACUUM, etc.) as recommendation
  scripts that the DBA will review and execute manually.
- Example output format: "Recommendation: Run the following script → CREATE INDEX ..."

Consider PostgreSQL-specific features like CTEs, window functions, and partial indexes.""",
        tools=["PostgresQueryAgent"], temperature=0.2)

    ORACLE_SECURITY_AUDITOR = AgentConfig(
        name="Oracle Security Auditor",
        agent_type=AgentType.SECURITY_AUDITOR,
        database_type=DatabaseType.ORACLE,
        description="Audits Oracle database security configurations and identifies vulnerabilities.",
        system_prompt="""You are an Oracle database security expert.

Your responsibilities:
- Audit user privileges and roles
- Identify excessive or unnecessary permissions
- Check password policies and profiles
- Review audit settings and configurations
- Identify publicly accessible objects
- Check for default or weak passwords
- Verify encryption settings

Security checks:
1. Review DBA_USERS for account status
2. Check DBA_SYS_PRIVS for powerful privileges
3. Audit DBA_ROLE_PRIVS for role assignments
4. Review DBA_TAB_PRIVS for object permissions
5. Check for PUBLIC grants
6. Verify password profile settings
7. Review audit trail configuration

⚠️  IMPORTANT — RECOMMENDATION MODE ONLY:
- You operate in READ-ONLY mode. Do NOT execute GRANT, REVOKE, or any DDL.
- Present all remediation steps as recommendation scripts for the DBA to review and apply.

Provide actionable remediation steps for findings.""",
        tools=["OracleQueryAgent"], temperature=0.0)

    POSTGRESQL_SECURITY_AUDITOR = AgentConfig(
        name="PostgreSQL Security Auditor",
        agent_type=AgentType.SECURITY_AUDITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Audits PostgreSQL database security configurations and identifies vulnerabilities.",
        system_prompt="""You are a PostgreSQL database security expert.

Your responsibilities:
- Audit user roles and permissions
- Identify excessive or unnecessary privileges
- Review pg_hba.conf authentication settings
- Check SSL/TLS configuration
- Identify security vulnerabilities in privileges
- Review row-level security policies
- Check for unencrypted connections

Security checks:
1. Review pg_roles for user permissions
2. Check pg_database for public access
3. Audit table and schema permissions
4. Review function and procedure privileges
5. Verify pg_hba.conf for secure authentication
6. Check for superuser accounts
7. Review connection encryption settings

⚠️  IMPORTANT — RECOMMENDATION MODE ONLY:
- You operate in READ-ONLY mode. Do NOT execute GRANT, REVOKE, ALTER ROLE, or any DDL.
- Present all remediation steps as recommendation scripts for the DBA to review and apply.

Provide actionable remediation steps for findings.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_CPU_ANOMALY = AgentConfig(
        name="PostgreSQL CPU Anomaly Detector",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with CPU anomalies in the last 6 hours.",
        system_prompt="""You are a PostgreSQL performance monitoring specialist focused on CPU anomaly detection.

Your task:
- Query pg_stat_database and system metrics to find hosts with unusual CPU patterns
- Identify hosts where CPU usage exceeded normal thresholds in the last 6 hours
- Analyze active queries that might be causing CPU spikes

Analysis approach:
1. Query current CPU-intensive queries using pg_stat_activity
2. Review pg_stat_statements for high CPU consumers
3. Check for missing indexes causing sequential scans
4. Identify queries with high execution time and CPU cost
5. Provide recommendations to reduce CPU load

Report: Host name, CPU %, time period, suspected queries, and remediation steps.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_MEMORY_ANOMALY = AgentConfig(
        name="PostgreSQL Memory Anomaly Detector",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with memory anomalies in the last 24 hours.",
        system_prompt="""You are a PostgreSQL performance monitoring specialist focused on memory anomaly detection.

Your task:
- Identify hosts with unusual memory consumption patterns in the last 24 hours
- Analyze memory usage from PostgreSQL buffer cache and work_mem

Analysis approach:
1. Check shared_buffers usage and effectiveness
2. Review cache hit ratios to assess memory efficiency
3. Identify queries with high work_mem or temp file usage
4. Check for connection pooling issues causing memory bloat
5. Analyze pg_stat_database for memory-related metrics

Report: Host name, memory usage %, time period, memory consumers, and optimization recommendations.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_CPU_TREND = AgentConfig(
        name="PostgreSQL CPU Trend Analyzer",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows CPU usage trend for a specific host over the last 12 hours.",
        system_prompt="""You are a PostgreSQL performance analyst specializing in CPU trend analysis.

Your task:
- Generate CPU usage trends for the specified host over the last 12 hours
- Identify peak usage periods and patterns
- Correlate CPU spikes with specific queries or operations

Analysis approach:
1. Query historical CPU metrics via pg_stat_statements
2. Identify recurring CPU-intensive operations
3. Check for batch jobs or scheduled tasks
4. Analyze connection count trends

Report: Hourly CPU trend data, peak periods, pattern analysis, and recommendations.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_FILESYSTEM_TREND = AgentConfig(
        name="PostgreSQL Filesystem Usage Trend",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows filesystem usage trends for the last 7 days.",
        system_prompt="""You are a PostgreSQL capacity planning specialist focused on storage trends.

Your task:
- Analyze filesystem usage trends over the last 7 days
- Identify databases and tables with rapid growth
- Predict storage capacity issues

Analysis approach:
1. Query pg_database_size() for database size trends
2. Check pg_total_relation_size() for large tables
3. Review pg_stat_user_tables for table bloat
4. Analyze WAL directory size and archiving status
5. Identify temp file usage from pg_stat_database

Report: Daily storage growth, top growing objects, projected capacity exhaustion date, cleanup recommendations.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_MOUNT_FREE_SPACE = AgentConfig(
        name="PostgreSQL Mount Free Space Checker",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies which host mount has the lowest free space in the last 30 days.",
        system_prompt="""You are a PostgreSQL storage management specialist.

Your task:
- Identify PostgreSQL host mounts with lowest free disk space over the last 30 days
- Monitor data directory, WAL directory, and temp directory space

Analysis approach:
1. Check database data directory space usage
2. Review WAL (pg_wal) directory space consumption
3. Analyze temp file directory usage
4. Identify candidates for vacuum and bloat reduction

Report: Mount point, free space GB, free space %, trend over 30 days, criticality level, remediation steps.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_EBS_SAVINGS = AgentConfig(
        name="PostgreSQL EBS Cost Optimizer",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies hosts with highest estimated EBS savings potential in the last 30 days.",
        system_prompt="""You are a PostgreSQL cloud cost optimization specialist focused on EBS storage.

Your task:
- Identify PostgreSQL instances with over-provisioned EBS storage
- Calculate potential savings from right-sizing storage

Analysis approach:
1. Calculate actual storage utilization percentage
2. Identify databases with excessive free space
3. Review storage growth patterns to right-size
4. Estimate cost savings from downsizing

Report: Host, current EBS size, actual usage, over-provisioned GB, estimated monthly savings, recommended size.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_WAL_MOUNT_CANDIDATES = AgentConfig(
        name="PostgreSQL WAL Mount Optimizer",
        agent_type=AgentType.CAPACITY_PLANNER,
        database_type=DatabaseType.POSTGRESQL,
        description="Shows cost-saving candidates for WAL mount optimization in the last 30 days.",
        system_prompt="""You are a PostgreSQL storage optimization specialist focused on WAL management.

Your task:
- Identify opportunities to optimize WAL storage configuration
- Analyze WAL generation rate and archiving efficiency

Analysis approach:
1. Review WAL generation rate (pg_stat_wal)
2. Check WAL archiving status and lag
3. Identify excessive WAL retention
4. Review wal_keep_size and max_wal_size settings

Report: Host, WAL generation rate, archive lag, storage consumption, optimization recommendations, estimated savings.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    POSTGRESQL_REPLICATION_LAG = AgentConfig(
        name="PostgreSQL Replication Lag Monitor",
        agent_type=AgentType.PERFORMANCE_MONITOR,
        database_type=DatabaseType.POSTGRESQL,
        description="Identifies clusters with highest replication lag in the last 6 hours.",
        system_prompt="""You are a PostgreSQL replication monitoring specialist.

Your task:
- Monitor replication lag across all PostgreSQL clusters
- Identify standby servers falling behind primary

Analysis approach:
1. Query pg_stat_replication for lag metrics
2. Check replay_lag, write_lag, and flush_lag
3. Review wal_sender and wal_receiver status
4. Identify network or disk bottlenecks
5. Check for long-running transactions blocking replay

Report: Cluster name, standby host, lag duration, lag size (bytes), root cause, remediation steps.""",
        tools=["PostgresQueryAgent"], temperature=0.0)

    @classmethod
    def get_all_templates(cls) -> list[AgentConfig]:
        return [
            cls.ORACLE_PERFORMANCE_MONITOR,
            cls.POSTGRESQL_PERFORMANCE_MONITOR,
            cls.ORACLE_TROUBLESHOOTER,
            cls.POSTGRESQL_TROUBLESHOOTER,
            cls.ORACLE_QUERY_OPTIMIZER,
            cls.POSTGRESQL_QUERY_OPTIMIZER,
            cls.ORACLE_SECURITY_AUDITOR,
            cls.POSTGRESQL_SECURITY_AUDITOR,
            cls.POSTGRESQL_CPU_ANOMALY,
            cls.POSTGRESQL_MEMORY_ANOMALY,
            cls.POSTGRESQL_CPU_TREND,
            cls.POSTGRESQL_FILESYSTEM_TREND,
            cls.POSTGRESQL_MOUNT_FREE_SPACE,
            cls.POSTGRESQL_EBS_SAVINGS,
            cls.POSTGRESQL_WAL_MOUNT_CANDIDATES,
            cls.POSTGRESQL_REPLICATION_LAG,
        ]

    @classmethod
    def get_templates_by_database(cls, database_type: DatabaseType) -> list[AgentConfig]:
        return [t for t in cls.get_all_templates() if t.database_type == database_type]


# ── AgentManager — file-backed JSON, same as Streamlit ───────────────────────

class AgentManager:

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            storage_path = os.getenv("AGENTS_DIR", "data/agents")
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.storage_path, f"{name.replace(' ', '_').lower()}.json")

    def save_agent(self, agent: AgentConfig) -> bool:
        try:
            agent.updated_at = datetime.now().isoformat()
            with open(self._path(agent.name), "w", encoding="utf-8") as f:
                json.dump(agent.to_dict(), f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving agent: {e}")
            return False

    def load_agent(self, agent_name: str) -> AgentConfig | None:
        try:
            with open(self._path(agent_name), encoding="utf-8") as f:
                return AgentConfig.from_dict(json.load(f))
        except Exception:
            return None

    def list_agents(self) -> list[str]:
        try:
            return [
                f.replace(".json", "").replace("_", " ").title()
                for f in os.listdir(self.storage_path)
                if f.endswith(".json")
            ]
        except Exception:
            return []

    def delete_agent(self, agent_name: str) -> bool:
        try:
            p = self._path(agent_name)
            if os.path.exists(p):
                os.remove(p)
                return True
            return False
        except Exception:
            return False


# ── AGENT_PLAYBOOKS — identical to Streamlit ─────────────────────────────────

AGENT_PLAYBOOKS = {
    "Oracle Performance Check": {
        "agent_type":    AgentType.PERFORMANCE_MONITOR,
        "database_type": DatabaseType.ORACLE,
        "queries": [
            "Check for long-running queries in the last hour",
            "Identify top 10 SQL statements by CPU usage",
            "Show tablespace usage and identify those over 80% full",
            "Check for blocking sessions",
        ],
    },
    "PostgreSQL Performance Check": {
        "agent_type":    AgentType.PERFORMANCE_MONITOR,
        "database_type": DatabaseType.POSTGRESQL,
        "queries": [
            "Show cache hit ratio and identify if it's below 99%",
            "Find long-running queries over 5 minutes",
            "Identify tables needing vacuum",
            "Show top 10 slowest queries by total execution time",
        ],
    },
    "Oracle Health Check": {
        "agent_type":    AgentType.TROUBLESHOOTER,
        "database_type": DatabaseType.ORACLE,
        "queries": [
            "Check for invalid objects",
            "Review alert log for recent errors",
            "Check failed jobs in the last 24 hours",
            "Verify backup completion status",
        ],
    },
    "PostgreSQL Health Check": {
        "agent_type":    AgentType.TROUBLESHOOTER,
        "database_type": DatabaseType.POSTGRESQL,
        "queries": [
            "Check replication lag",
            "Identify bloated tables",
            "Show connection pool usage",
            "Check for disk space issues",
        ],
    },
}


# ── SQL helpers ───────────────────────────────────────────────────────────────

def _clean_sql(sql: str, db_type: str) -> str:
    """Strip LangChain markdown/formatting artifacts — same as Streamlit."""
    sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```\s*", "", sql)
    sql = sql.strip().strip('"').strip("'").strip().strip("`")
    sql = " ".join(sql.split())
    if db_type == "oracle" and sql.endswith(";"):
        sql = sql[:-1].strip()
    return sql


# ── READ-ONLY keyword guard (mirrors Streamlit's allow_select_only=True) ──────
# Matches Streamlit's PostgresQuery / OracleQuery tools which call
# run_postgres_query(sql) / run_oracle_query(sql) with validate_sql(allow_select_only=True).
# ALL DDL and DML modification statements are blocked so agents can only
# ANALYZE and RECOMMEND — never mutate the database directly.

_READONLY_BLOCKED = {
    "DROP", "TRUNCATE", "DELETE",
    "CREATE", "ALTER",
    "INSERT", "UPDATE",
    "GRANT", "REVOKE",
}


def _blocked_keyword(sql: str) -> str | None:
    """Return the first blocked keyword found in sql, or None if safe (SELECT-only).

    Mirrors Streamlit's validate_sql(allow_select_only=True) used by the
    PostgresQuery / OracleQuery tools that back all agent templates.
    """
    su = sql.upper().strip()
    for kw in _READONLY_BLOCKED:
        if (f" {kw} " in f" {su} " or
                su.startswith(f"{kw} ") or su == kw or
                su.endswith(f" {kw}")):
            return kw
    return None


def _get_active_cs(db_type: str, username: str = "agent") -> tuple[str | None, str | None]:
    """Return (connection_string, error_message).
    Fully thread-safe: never touches current_app.
    Resolution order: env var → app config (if in context) → repo-relative absolute path.
    """
    # 1. Explicit env override
    raw = os.getenv("DB_CONNECTIONS_FILE")

    # 2. Try Flask app config only if we already have an active app context
    if not raw:
        try:
            from flask import has_app_context, current_app
            if has_app_context():
                raw = current_app.config.get("DB_CONNECTIONS_FILE")
        except Exception:
            pass

    # 3. Always-safe absolute fallback: <repo_root>/data/db_connections.json
    if raw:
        f = Path(raw)
    else:
        f = Path(__file__).resolve().parent / "data" / "db_connections.json"

    if not f.exists():
        return None, f"Connections file not found at {f}. Add a connection first."
    try:
        conns = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"Could not read connections file: {e}"
    # Per-user active connection
    if username and username != "agent":
        try:
            import os as _os
            base = _os.getenv("BASE_DIR") or str(Path(__file__).resolve().parent)
            from app.api.user_state import get_active_conn_id
            cid = get_active_conn_id(base, username, db_type)
            if cid and cid in conns and conns[cid].get("db_type") == db_type:
                return conns[cid]["connection_string"], None
        except Exception:
            pass
    # Fallback: global is_active
    for c in conns.values():
        if c.get("db_type") == db_type and c.get("is_active"):
            return c["connection_string"], None
    return None, f"No active {db_type} connection. Activate one in Database Connections."


# ── Oracle query runner for agents ────────────────────────────────────────────

def _run_oracle_for_agent(sql: str, username: str = "agent") -> str:
    """
    Mirrors Streamlit run_oracle_query_for_agent():
    PII validation → keyword block → execute → PII redaction → 100-row cap → logging
    """
    sys.path.insert(0, str(Path(__file__).parent))

    sql = _clean_sql(sql, "oracle")

    # Dangerous keyword block — same as Streamlit
    kw = _blocked_keyword(sql)
    if kw:
        try:
            from activity_logger import log_safety_block
            log_safety_block(username, sql, f"❌ {kw} blocked", source="ai_agent")
        except Exception:
            pass
        return f"🛡️ BLOCKED: ❌ {kw} operations are blocked for safety"

    # PII check
    pii_details = {}
    try:
        from pii_blacklist_protection import PIIBlacklist, PIIQueryValidator, log_pii_access
        bl = PIIBlacklist("pii_blacklist.json")
        is_allowed, message, pii_details = PIIQueryValidator(bl).validate_query(sql, username, "oracle")
        if not is_allowed:
            log_pii_access("blocked_query", username, {
                "sql": sql, "reason": pii_details.get("reason"),
                "blocked_tables": pii_details.get("blocked_tables", []),
                "source": "ai_agent",
            })
            return f"🚫 AI AGENT PII PROTECTION\n\n{message}"
        if pii_details.get("pii_warning"):
            log_pii_access("pii_query_ai_agent", username, {
                "sql": sql, "pii_columns": pii_details.get("pii_columns", []),
                "source": "ai_agent",
            })
    except (ImportError, Exception):
        pass

    cs, err = _get_active_cs("oracle", username)
    if not cs:
        return f"Oracle connection unavailable: {err}"

    t0 = time.time()
    try:
        import oracledb
        u, rest = cs.split("@", 1)
        usr, pw = u.split("/", 1)
        conn = oracledb.connect(user=usr, password=pw, dsn=rest)
        cur  = conn.cursor()
        cur.execute(sql)
        elapsed = round((time.time() - t0) * 1000, 1)

        if cur.description:
            import pandas as pd
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            cur.close(); conn.close()
            df = pd.DataFrame(rows, columns=cols)

            # PII redaction
            if pii_details.get("pii_columns") or pii_details.get("pii_warning"):
                try:
                    from pii_blacklist_protection import redact_pii_dataframe, PIIBlacklist, log_pii_access
                    rdf, summary = redact_pii_dataframe(df, pii_details.get("pii_columns", []),
                                                        PIIBlacklist("pii_blacklist.json"), "oracle")
                    log_pii_access("pii_redacted_ai_agent", username, {
                        "sql": sql, "rows": len(df),
                        "redacted_columns": pii_details.get("pii_columns", []), "source": "ai_agent",
                    })
                    result = f"🛡️ PII PROTECTED (AI Agent)\n\n{summary}\n\n{rdf.head(100).to_string(index=False)}"
                    if len(rdf) > 100:
                        result += f"\n\n... and {len(rdf)-100} more rows"
                    return result
                except Exception:
                    pass

            try:
                from activity_logger import log_sql_execution
                log_sql_execution(username=f"{username}_agent", sql=sql, db_type="Oracle",
                                  execution_time=elapsed, rows_affected=len(rows), success=True)
            except Exception:
                pass

            if len(df) > 100:
                return (f"Query returned {len(df)} rows. Showing first 100:\n\n"
                        f"{df.head(100).to_string(index=False)}\n\n... and {len(df)-100} more rows")
            return df.to_string(index=False)

        else:
            conn.commit(); cur.close(); conn.close()
            try:
                from activity_logger import log_sql_execution
                log_sql_execution(username=f"{username}_agent", sql=sql, db_type="Oracle",
                                  execution_time=elapsed, rows_affected=0, success=True)
            except Exception:
                pass
            return "✓ Query executed successfully."

    except Exception as exc:
        elapsed = round((time.time() - t0) * 1000, 1)
        err_msg = str(exc)
        try:
            from activity_logger import log_sql_execution
            log_sql_execution(username=f"{username}_agent", sql=sql, db_type="Oracle",
                              execution_time=elapsed, success=False, error=err_msg)
        except Exception:
            pass
        return f"❌ Oracle Error: {err_msg}\n\nSQL executed: {sql[:200]}"


# ── PostgreSQL query runner for agents ───────────────────────────────────────

def _run_postgres_for_agent(sql: str, username: str = "agent") -> str:
    """
    Mirrors Streamlit run_postgres_query_for_agent():
    PII validation → keyword block → execute → PII redaction → 100-row cap → logging
    """
    sys.path.insert(0, str(Path(__file__).parent))

    sql = _clean_sql(sql, "postgres")

    kw = _blocked_keyword(sql)
    if kw:
        try:
            from activity_logger import log_safety_block
            log_safety_block(username, sql, f"❌ {kw} blocked", source="ai_agent")
        except Exception:
            pass
        return f"🛡️ BLOCKED: ❌ {kw} operations are blocked for safety"

    pii_details = {}
    try:
        from pii_blacklist_protection import PIIBlacklist, PIIQueryValidator, log_pii_access
        bl = PIIBlacklist("pii_blacklist.json")
        is_allowed, message, pii_details = PIIQueryValidator(bl).validate_query(sql, username, "postgresql")
        if not is_allowed:
            log_pii_access("blocked_query", username, {
                "sql": sql, "reason": pii_details.get("reason"),
                "blocked_tables": pii_details.get("blocked_tables", []), "source": "ai_agent",
            })
            return f"🚫 AI AGENT PII PROTECTION\n\n{message}"
        if pii_details.get("pii_warning"):
            log_pii_access("pii_query_ai_agent", username, {
                "sql": sql, "pii_columns": pii_details.get("pii_columns", []),
                "action": pii_details.get("action", "redact"), "source": "ai_agent",
            })
    except (ImportError, Exception):
        pass

    cs, err = _get_active_cs("postgres", username)
    if not cs:
        return f"PostgreSQL connection unavailable: {err}"

    t0 = time.time()
    conn = None
    try:
        import psycopg2
        conn = psycopg2.connect(cs)
        cur  = conn.cursor()
        cur.execute(sql)
        elapsed = round((time.time() - t0) * 1000, 1)

        if cur.description:
            import pandas as pd
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            cur.close()
            df = pd.DataFrame(rows, columns=cols)

            # PII redaction
            if pii_details.get("pii_columns") or pii_details.get("pii_warning"):
                try:
                    from pii_blacklist_protection import redact_pii_dataframe, PIIBlacklist, log_pii_access
                    rdf, summary = redact_pii_dataframe(df, pii_details.get("pii_columns", []),
                                                        PIIBlacklist("pii_blacklist.json"), "postgresql")
                    log_pii_access("pii_redacted_ai_agent", username, {
                        "sql": sql, "rows": len(df),
                        "redacted_columns": pii_details.get("pii_columns", []), "source": "ai_agent",
                    })
                    result = f"🛡️ PII PROTECTED (AI Agent)\n\n{summary}\n\n{rdf.head(100).to_string(index=False)}"
                    if len(rdf) > 100:
                        result += f"\n\n... and {len(rdf)-100} more rows"
                    conn.close()
                    return result
                except Exception:
                    pass

            try:
                from activity_logger import log_sql_execution
                log_sql_execution(username=f"{username}_agent", sql=sql, db_type="PostgreSQL",
                                  execution_time=elapsed, rows_affected=len(rows), success=True)
            except Exception:
                pass

            conn.close()
            if len(df) > 100:
                return (f"Query returned {len(df)} rows. Showing first 100:\n\n"
                        f"{df.head(100).to_string(index=False)}\n\n... and {len(df)-100} more rows")
            return df.to_string(index=False)

        else:
            conn.commit(); cur.close(); conn.close()
            try:
                from activity_logger import log_sql_execution
                log_sql_execution(username=f"{username}_agent", sql=sql, db_type="PostgreSQL",
                                  execution_time=elapsed, rows_affected=0, success=True)
            except Exception:
                pass
            return "✓ Query executed successfully."

    except Exception as exc:
        elapsed = round((time.time() - t0) * 1000, 1)
        err_msg = str(exc)
        try:
            from activity_logger import log_sql_execution
            log_sql_execution(username=f"{username}_agent", sql=sql, db_type="PostgreSQL",
                              execution_time=elapsed, success=False, error=err_msg)
        except Exception:
            pass
        if conn:
            try: conn.rollback(); conn.close()
            except Exception: pass
        return f"❌ PostgreSQL Error: {err_msg}\n\nSQL executed: {sql[:200]}"


# ── Build LangChain Tool objects — exact tool descriptions from Streamlit ─────

def build_agent_tools(username: str = "agent") -> dict[str, Tool]:
    """Returns OracleQueryAgent and PostgresQueryAgent Tool objects.

    These tools mirror Streamlit's OracleQuery / PostgresQuery tools which use
    validate_sql(allow_select_only=True).  Agents may ONLY run SELECT statements
    and read-only system views.  ALL DDL (CREATE, ALTER, DROP) and DML
    (INSERT, UPDATE, DELETE, TRUNCATE) are blocked so the Query Optimizer and
    other agents produce RECOMMENDATIONS — they never mutate the database.
    """
    _BLOCKED_LIST = ", ".join(sorted(_READONLY_BLOCKED))
    return {
        "OracleQueryAgent": Tool(
            name="OracleQueryAgent",
            func=lambda sql: _run_oracle_for_agent(sql, username),
            description=(
                "Execute READ-ONLY SQL queries on Oracle database for analysis and monitoring.\n\n"
                "IMPORTANT RULES:\n"
                "1. Write PLAIN SQL only - NO markdown, NO code blocks, NO backticks\n"
                "2. Do NOT add quotes around the SQL\n"
                "3. Do NOT use semicolons at end (Oracle driver doesn't accept them)\n"
                "4. Example: SELECT * FROM v$session WHERE status='ACTIVE'\n"
                "5. NOT: ```sql SELECT ... ``` or \"SELECT ...\" or SELECT ...;\n\n"
                "⚠️  READ-ONLY MODE — for analysis and recommendations only.\n"
                f"Blocked (will return an error): {_BLOCKED_LIST}\n"
                "Allowed: SELECT and read-only system views (v$session, dba_*, etc.)\n\n"
                "For Query Optimization: run EXPLAIN PLAN or query execution stats — "
                "present index/SQL recommendations as scripts for the DBA to review and apply."
            ),
        ),
        "PostgresQueryAgent": Tool(
            name="PostgresQueryAgent",
            func=lambda sql: _run_postgres_for_agent(sql, username),
            description=(
                "Execute READ-ONLY SQL queries on PostgreSQL database for analysis and monitoring.\n\n"
                "IMPORTANT RULES:\n"
                "1. Write PLAIN SQL only - NO markdown, NO code blocks, NO backticks\n"
                "2. Do NOT add quotes around the SQL\n"
                "3. Example: SELECT * FROM pg_stat_activity WHERE state='active'\n"
                "4. NOT: ```sql SELECT ... ``` or \"SELECT ...\"\n\n"
                "⚠️  READ-ONLY MODE — for analysis and recommendations only.\n"
                f"Blocked (will return an error): {_BLOCKED_LIST}\n"
                "Allowed: SELECT and read-only system views (pg_stat_*, pg_*, etc.)\n\n"
                "For Query Optimization: use EXPLAIN ANALYZE to analyse plans — "
                "present index/SQL recommendations as scripts for the DBA to review and apply."
            ),
        ),
    }


# ── AgentExecutor — exact copy of Streamlit's AgentExecutor class ─────────────

class AgentExecutor:
    """Executes AI agents with real LangChain REACT loop — same as Streamlit."""

    def __init__(self, llm, tools_map: dict[str, Any]):
        self.llm       = llm
        self.tools_map = tools_map

    def execute_agent(self, agent: AgentConfig, user_query: str) -> str:
        from langchain.agents import initialize_agent
        from langchain.agents import AgentType as LCAgentType

        agent_tools = [self.tools_map[t] for t in agent.tools if t in self.tools_map]
        if not agent_tools:
            return f"Error: No valid tools configured for agent '{agent.name}'"

        enhanced_prompt = (
            f"{agent.system_prompt}\n\n"
            "CRITICAL INSTRUCTIONS FOR TOOL USAGE:\n"
            "When you need to use a tool, you MUST use this EXACT format:\n\n"
            "Action: ToolName\n"
            "Action Input: your input here\n\n"
            "Then wait for the observation before proceeding.\n\n"
            f"AVAILABLE TOOLS:\n"
            + "\n".join(f"- {t.name}: {t.description}" for t in agent_tools)
            + "\n\nIMPORTANT: Do NOT write conversational responses when you should be using a tool.\n"
            "ALWAYS use the Action/Action Input format when calling tools.\n"
            'After getting the observation, provide a clear final answer starting with "Final Answer:".\n'
        )

        is_ollama = "ollama" in str(type(self.llm)).lower()
        max_iter  = agent.max_iterations * 2 if is_ollama else agent.max_iterations

        executor = initialize_agent(
            agent_tools, self.llm,
            agent=LCAgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            max_iterations=max_iter,
            handle_parsing_errors=True,
            early_stopping_method="generate",
            agent_kwargs={"prefix": enhanced_prompt},
        )

        try:
            return executor.run(user_query)
        except Exception as e:
            err = str(e)
            if "iteration limit" in err.lower() or "time limit" in err.lower():
                return (
                    "⚠️ The query took too long to complete. This can happen with complex queries on Ollama.\n\n"
                    "💡 Try:\n"
                    "1. Asking a simpler, more specific question\n"
                    "2. Using a smaller Ollama model (e.g., qwen3-coder:7b instead of 30b)\n"
                    "3. Using OpenAI GPT-4 for better performance\n\n"
                    "Partial result: The agent was working on your query but needed more time."
                )
            if "parsing error" in err.lower():
                return (
                    "⚠️ The AI model didn't follow the expected format. This can happen with some models like Ollama.\n\n"
                    "💡 Try:\n"
                    "1. Rephrasing your query\n"
                    "2. Using OpenAI GPT-4 for better agent performance\n"
                    "3. Using the AI Chat feature instead of Agents\n\n"
                    f"Technical error: {err}"
                )
            if "connection" in err.lower() or "pool" in err.lower():
                return f"⚠️ Database connection error. Make sure your database is connected and accessible.\n\nError: {err}"
            return f"Error executing agent: {err}"
