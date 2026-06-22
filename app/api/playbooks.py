"""
app/api/playbooks.py — DBA Playbook execution endpoints.

Reads SQL files from the sql/ directory (mirrors Streamlit behaviour exactly).

Routes:
  GET  /api/playbooks/list              → all playbooks for oracle + postgres
  POST /api/playbooks/run               → execute a named playbook
  GET  /api/playbooks/sql/<db>/<key>    → return raw SQL for a playbook
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime, UTC

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from activity_logger import log_activity, log_sql_execution, log_feature_usage, log_error

playbooks_bp = Blueprint("playbooks", __name__)

# ── Playbook catalogues (mirrors Streamlit app.py exactly) ────────────────────

ORACLE_PLAYBOOKS: dict[str, str] = {
    "long_running_sqls":       "1) Long Running SQLs",
    "sql_monitoring":          "2) SQL Monitoring",
    "blocking_sessions":       "3) Blocking Sessions",
    "find_blocking_sql_text":  "4) Find Blocking SQL Text",
    "invalid_objects":         "5) Invalid Objects",
    "unusable_indexes":        "6) Unusable Indexes",
    "failed_jobs":             "7) Failed Jobs",
    "datapump_jobs":           "8) Datapump Jobs",
    "sessions_per_machine":    "9) Sessions per Machine",
    "application_lrq":         "10) Application Long Running Queries",
    "db_size":                 "11) Database Size",
    "tablespace_usage_high":   "12) Tablespace Usage High",
    "fra_usage_dba":           "13) FRA Usage (DBA)",
    "sga_pga_advisor":         "14) SGA/PGA Advisor",
    "check_profile_idle":      "15) Check Profile Idle",
    "check_triggers":          "16) Check Triggers",
}

POSTGRES_PLAYBOOKS: dict[str, str] = {
    "pg_database_size":        "1) Database Size",
    "pg_active_connections":   "2) Active Connections",
    "pg_long_running_queries": "3) Long Running Queries",
    "pg_blocking_queries":     "4) Blocking Queries",
    "pg_table_sizes":          "5) Table Sizes",
    "pg_index_usage":          "6) Index Usage",
    "pg_cache_hit_ratio":      "7) Cache Hit Ratio",
    "pg_vacuum_stats":         "8) Vacuum Statistics",
    "pg_replication_status":   "9) Replication Status",
    "pg_locks_overview":       "10) Locks Overview",
    "pg_database_activity":    "11) Database Activity",
    "pg_slow_queries":         "12) Slow Queries Log",
}


def _sql_root() -> Path:
    """Resolve sql/ directory relative to the project root."""
    return Path(current_app.config.get("BASE_DIR", ".")) / "sql"


def _load_sql(db_type: str, key: str) -> str | None:
    """Load SQL from file. Returns None if not found."""
    root = _sql_root()
    candidates = [
        root / db_type / f"{key}.sql",      # sql/oracle/key.sql
        root / f"{key}.sql",                 # sql/key.sql  (legacy)
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _require_perm() -> tuple | None:
    perms = get_jwt().get("permissions", [])
    if "dba_playbooks" not in perms:
        return jsonify({"error": "dba_playbooks permission required"}), 403
    return None


# ── List ───────────────────────────────────────────────────────────────────────

@playbooks_bp.get("/list")
@jwt_required()
def list_playbooks():
    if err := _require_perm():
        return err
    return jsonify({
        "oracle":   [{"key": k, "label": v} for k, v in ORACLE_PLAYBOOKS.items()],
        "postgres": [{"key": k, "label": v} for k, v in POSTGRES_PLAYBOOKS.items()],
    }), 200


# ── Raw SQL ────────────────────────────────────────────────────────────────────

@playbooks_bp.get("/sql/<db_type>/<key>")
@jwt_required()
def get_playbook_sql(db_type: str, key: str):
    if err := _require_perm():
        return err
    sql = _load_sql(db_type, key)
    if not sql:
        return jsonify({"error": f"SQL file not found for {db_type}/{key}"}), 404
    return jsonify({"db_type": db_type, "key": key, "sql": sql}), 200


# ── Run ────────────────────────────────────────────────────────────────────────

@playbooks_bp.post("/run")
@jwt_required()
def run_playbook():
    if err := _require_perm():
        return err

    username = get_jwt_identity()
    data     = request.get_json(silent=True) or {}
    db_type  = (data.get("db_type") or "").lower()
    key      = (data.get("key") or "").strip()

    if db_type not in ("oracle", "postgres"):
        return jsonify({"error": "db_type must be oracle or postgres"}), 400
    if not key:
        return jsonify({"error": "key is required"}), 400

    # Validate key is in catalogue
    catalogue = ORACLE_PLAYBOOKS if db_type == "oracle" else POSTGRES_PLAYBOOKS
    if key not in catalogue:
        return jsonify({"error": f"Unknown playbook key: {key!r}"}), 400

    label = catalogue[key]

    # Load SQL from file
    sql = _load_sql(db_type, key)
    if not sql:
        return jsonify({"error": f"SQL file not found for {db_type}/{key}. "
                                  f"Check that sql/{db_type}/{key}.sql exists."}), 404

    # Resolve active connection
    conn_file = Path(current_app.config["DB_CONNECTIONS_FILE"])
    if not conn_file.exists():
        return jsonify({"error": "No connections file — add a connection first."}), 400

    import json as _json
    conns     = _json.loads(conn_file.read_text(encoding="utf-8"))
    active_cs = None
    # Per-user active connection
    try:
        from flask_jwt_extended import get_jwt_identity as _gji
        from app.api.user_state import get_active_conn_id
        _pu = _gji()
        base = current_app.config.get("BASE_DIR", ".")
        cid  = get_active_conn_id(base, _pu, db_type)
        if cid and cid in conns and conns[cid].get("db_type") == db_type:
            active_cs = conns[cid]["connection_string"]
    except Exception:
        pass
    if not active_cs:
        for c in conns.values():
            if c.get("db_type") == db_type and c.get("is_active"):
                active_cs = c["connection_string"]
                break

    if not active_cs:
        return jsonify({
            "error": f"No active {db_type} connection. "
                     "Activate one in Database Connections first."
        }), 400

    t0 = time.perf_counter()
    try:
        if db_type == "oracle":
            import oracledb
            user, rest = active_cs.split("@", 1)
            u, pw      = user.split("/", 1)
            conn       = oracledb.connect(user=u, password=pw, dsn=rest)
            cur        = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [[str(v) if v is not None else None for v in row]
                    for row in (cur.fetchall() if cur.description else [])]
            cur.close(); conn.close()
        else:
            import psycopg2
            conn = psycopg2.connect(active_cs)
            cur  = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [[str(v) if v is not None else None for v in row]
                    for row in (cur.fetchall() if cur.description else [])]
            cur.close(); conn.close()

        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        log_sql_execution(
            username=username, sql=f"[PLAYBOOK: {label}]\n{sql}",
            db_type=db_type, execution_time=elapsed,
            rows_affected=len(rows), success=True,
        )
        log_feature_usage(username, "playbooks", "run", f"{db_type}/{key}: {label}")

        return jsonify({
            "playbook":          label,
            "key":               key,
            "db_type":           db_type,
            "columns":           cols,
            "rows":              rows,
            "row_count":         len(rows),
            "execution_time_ms": elapsed,
            "executed_at":       datetime.now(UTC).isoformat(timespec="seconds"),
        }), 200

    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        log_sql_execution(
            username=username, sql=f"[PLAYBOOK: {label}]\n{sql}",
            db_type=db_type, execution_time=elapsed,
            success=False, error=str(exc),
        )
        log_error(username, "playbook_error", str(exc), context=f"{db_type}/{key}")
        return jsonify({
            "error":             str(exc),
            "playbook":          label,
            "execution_time_ms": elapsed,
        }), 500
