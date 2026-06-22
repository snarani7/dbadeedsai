"""
app/api/query.py  —  SQL execution with full 3-layer guardrail stack.

  Layer 1 – Content Filter  (generate endpoint only: validate the NL prompt)
  Layer 2 – SQL Safety      (all endpoints: blocks DDL/DML/dangerous functions)
  Layer 3 – PII Blacklist   (all endpoints: blocks PII tables, redacts PII columns in results)
"""
from __future__ import annotations
import json, re, sys, time, os
from pathlib import Path
from datetime import datetime, UTC
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

sys.path.insert(0, str(Path(__file__).parents[3]))
from sql_safety import validate_sql, get_safety_help
from content_filter import validate_chat_question
from pii_blacklist_protection import validate_pii, redact_pii_rows, log_pii_access
from activity_logger import (log_sql_execution, log_safety_block,
                              log_ai_query_generation, log_error, log_feature_usage)

query_bp = Blueprint("query", __name__)


# ── DB helpers ────────────────────────────────────────────────────────────────
def _active_conn(db_type, username: str = ""):
    f = Path(current_app.config.get("DB_CONNECTIONS_FILE",
             os.getenv("DB_CONNECTIONS_FILE", "data/db_connections.json")))
    if not f.exists():
        return None, "No connections file found — add a connection first."
    conns = json.loads(f.read_text())
    # Per-user active connection
    if username:
        try:
            base = current_app.config.get("BASE_DIR", ".")
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

def _run_oracle(cs, sql):
    import oracledb
    u, rest = cs.split("@", 1); usr, pw = u.split("/", 1)
    conn = oracledb.connect(user=usr, password=pw, dsn=rest); cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = [[str(v) if v is not None else None for v in r] for r in (cur.fetchall() if cur.description else [])]
    cur.close(); conn.close(); return cols, rows

def _run_postgres(cs, sql):
    import psycopg2
    conn = psycopg2.connect(cs); cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = [[str(v) if v is not None else None for v in r] for r in (cur.fetchall() if cur.description else [])]
    cur.close(); conn.close(); return cols, rows

def _require_perm():
    if "db_explorer" not in get_jwt().get("permissions", []):
        return jsonify({"error": "db_explorer permission required"}), 403


# ── /execute ──────────────────────────────────────────────────────────────────
@query_bp.post("/execute")
@jwt_required()
def execute_query():
    if err := _require_perm(): return err
    username = get_jwt_identity()
    data     = request.get_json(silent=True) or {}
    sql      = (data.get("sql") or "").strip()
    db_type  = (data.get("db_type") or "postgres").lower()
    if not sql: return jsonify({"error": "sql is required"}), 400

    # ── Layer 2: SQL Safety ───────────────────────────────────────────
    safe, smsg = validate_sql(sql, allow_select_only=True)
    if not safe:
        log_safety_block(username, sql, smsg, source="db_explorer")
        return jsonify({"error": "🚫 Blocked by SQL Safety Guardrail",
                        "detail": smsg, "safety_help": get_safety_help(),
                        "guardrail": "sql_safety"}), 400

    # ── Layer 3: PII Blacklist ────────────────────────────────────────
    pii_ok, pii_msg, pii_det = validate_pii(sql, username, db_type)
    if not pii_ok:
        log_safety_block(username, sql, pii_msg, source="pii_blacklist")
        log_pii_access("blocked_table", username,
                       {"sql": sql[:300], "db_type": db_type,
                        "blocked_tables": pii_det.get("blocked_tables", [])})
        return jsonify({"error": "🚫 Blocked by PII Guardrail", "detail": pii_msg,
                        "guardrail": "pii_blacklist",
                        "blocked_tables": pii_det.get("blocked_tables", [])}), 400

    pii_warn = pii_det.get("pii_warning", False)
    pii_cols = pii_det.get("pii_columns", [])
    if pii_warn:
        log_pii_access("pii_column_access", username,
                       {"sql": sql[:300], "db_type": db_type, "pii_columns": pii_cols, "action": "redact"})

    _quser = get_jwt_identity()
    cs, emsg = _active_conn(db_type, _quser)
    if not cs: return jsonify({"error": emsg}), 400

    t0 = time.perf_counter()
    try:
        cols, rows = _run_oracle(cs, sql) if db_type == "oracle" else _run_postgres(cs, sql)
        elapsed    = round((time.perf_counter() - t0) * 1000, 2)

        # ── Layer 3b: Redact PII columns in result ────────────────────
        redact_summary = None
        if pii_warn and pii_cols:
            rows, redact_summary = redact_pii_rows(cols, rows, pii_cols, db_type)
            log_pii_access("pii_redacted", username,
                           {"sql": sql[:300], "db_type": db_type,
                            "pii_columns": pii_cols, "rows_redacted": len(rows)})

        log_sql_execution(username=username, sql=sql, db_type=db_type,
                          execution_time=elapsed, rows_affected=len(rows), success=True)

        resp = {"columns": cols, "rows": rows, "row_count": len(rows),
                "execution_time_ms": elapsed, "db_type": db_type,
                "executed_at": datetime.now(UTC).isoformat(timespec="seconds")}
        if pii_warn:
            resp.update({"pii_warning": True, "pii_message": pii_msg,
                         "pii_columns": pii_cols, "redaction_summary": redact_summary})
        if pii_det.get("aggregated"):
            resp["pii_note"] = pii_msg
        return jsonify(resp), 200
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        log_sql_execution(username=username, sql=sql, db_type=db_type,
                          execution_time=elapsed, success=False, error=str(exc))
        log_error(username, "query_execution_error", str(exc), context=f"db_type={db_type}")
        return jsonify({"error": str(exc), "execution_time_ms": elapsed}), 500


# ── /explain ──────────────────────────────────────────────────────────────────
@query_bp.post("/explain")
@jwt_required()
def explain_query():
    if err := _require_perm(): return err
    username = get_jwt_identity()
    data    = request.get_json(silent=True) or {}
    sql     = (data.get("sql") or "").strip()
    db_type = (data.get("db_type") or "postgres").lower()
    if not sql: return jsonify({"error": "sql is required"}), 400

    safe, smsg = validate_sql(sql, allow_select_only=True)
    if not safe:
        log_safety_block(username, sql, smsg, source="db_explorer_explain")
        return jsonify({"error": "Blocked by SQL Safety", "detail": smsg}), 400

    explain = f"EXPLAIN {sql}" if db_type == "postgres" else f"EXPLAIN PLAN FOR {sql}"
    _euser = get_jwt_identity()
    cs, emsg = _active_conn(db_type, _euser)
    if not cs: return jsonify({"error": emsg}), 400

    t0 = time.perf_counter()
    try:
        cols, rows = _run_oracle(cs, explain) if db_type == "oracle" else _run_postgres(cs, explain)
        elapsed    = round((time.perf_counter() - t0) * 1000, 2)
        log_feature_usage(username, "db_explorer", "explain", f"db_type={db_type}")
        return jsonify({"plan": rows, "columns": cols, "execution_time_ms": elapsed}), 200
    except Exception as exc:
        log_error(username, "explain_error", str(exc))
        return jsonify({"error": str(exc)}), 500


# ── /generate ─────────────────────────────────────────────────────────────────
@query_bp.post("/generate")
@jwt_required()
def generate_sql():
    if err := _require_perm(): return err
    username = get_jwt_identity()
    data    = request.get_json(silent=True) or {}
    prompt  = (data.get("prompt") or "").strip()
    db_type = (data.get("db_type") or "postgres").lower()
    if not prompt: return jsonify({"error": "prompt is required"}), 400

    # ── Layer 1: Content Filter on NL prompt ─────────────────────────
    cf_ok, cf_msg = validate_chat_question(prompt)
    if not cf_ok:
        log_safety_block(username, prompt, cf_msg, source="generate_content_filter")
        return jsonify({"error": "🚫 Blocked by Content Filter",
                        "detail": cf_msg, "guardrail": "content_filter"}), 400

    complexity       = (data.get("complexity") or "Medium").strip()
    include_comments = bool(data.get("include_comments", True))
    optimize_query   = bool(data.get("optimize_query", True))

    try:
        from langchain.schema import HumanMessage, SystemMessage
        from app.api.llm_settings import _get_user_cfg, build_llm
        user_cfg = _get_user_cfg(username)
        llm      = build_llm(user_cfg, streaming=False)

        complexity_map = {
            "Simple":   "Generate a simple, straightforward SQL query.",
            "Medium":   "Generate a moderately complex SQL query with JOINs if needed.",
            "Advanced": "Generate an advanced SQL query with CTEs, window functions, or complex joins as appropriate.",
        }
        complexity_instr = complexity_map.get(complexity, complexity_map["Medium"])
        comment_instr    = "Add clear inline comments to explain complex parts of the query." if include_comments else "Do not include any comments."
        optimize_instr   = "Optimise the query for performance with proper indexing hints and efficient joins." if optimize_query else ""
        oracle_note      = "\nIMPORTANT: Do NOT include a semicolon at the end — Oracle driver rejects them." if db_type == "oracle" else ""

        system = (
            f"You are an expert {db_type.upper()} Database Administrator and SQL developer.\n"
            "Generate ONLY the SQL query — no explanations, no markdown code fences, no preamble.\n"
            f"{complexity_instr}\n"
            f"{comment_instr}\n"
            f"{optimize_instr}"
            f"{oracle_note}\n"
            "CRITICAL SAFETY: Generate ONLY SELECT queries. "
            "NEVER generate CREATE, ALTER, DROP, DELETE, UPDATE, INSERT, TRUNCATE, or EXEC."
        )
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        sql  = resp.content.strip()

        # Strip markdown fences — Gemini sometimes wraps output in ```sql...```
        # despite instructions. Must be done BEFORE safety check.
        _fence = re.search(r'```(?:sql|SQL)?\s*\n?([\s\S]*?)```', sql)
        if _fence:
            sql = _fence.group(1).strip()
        # Also strip leading/trailing backtick lines
        sql = re.sub(r'^```[a-zA-Z]*\n?', '', sql).strip()
        sql = re.sub(r'\n?```$', '', sql).strip()

        # Extract first SQL statement — handles preamble text like
        # "Here is your query:\nSELECT..." that Gemini sometimes adds
        # Find first line that starts with a valid SQL keyword
        _sql_keywords = ('SELECT', 'WITH', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN', 'TABLE')
        _lines = sql.split('\n')
        for _i, _line in enumerate(_lines):
            if _line.strip().upper().startswith(_sql_keywords):
                sql = '\n'.join(_lines[_i:]).strip()
                break

        # Strip trailing semicolon — Oracle driver rejects them, and it avoids
        # stacked-statement false positives in the safety check
        sql = sql.rstrip(';').rstrip()

        # ── Layer 2: SQL Safety on generated SQL ──────────────────────
        safe, smsg = validate_sql(sql, allow_select_only=True)
        if not safe:
            log_safety_block(username, sql, smsg, source="ai_generator")
            return jsonify({"error": "⚠️ AI generated unsafe SQL — blocked",
                            "detail": smsg, "guardrail": "sql_safety"}), 400

        # ── Layer 3: PII check on generated SQL ───────────────────────
        pii_ok, pii_msg, pii_det = validate_pii(sql, username, db_type)
        if not pii_ok:
            log_safety_block(username, sql, pii_msg, source="ai_generator_pii")
            log_pii_access("generated_sql_blocked", username,
                           {"sql": sql[:300], "prompt": prompt[:200], "db_type": db_type,
                            "blocked_tables": pii_det.get("blocked_tables", [])})
            return jsonify({"error": "⚠️ AI SQL accesses PII tables — blocked",
                            "detail": pii_msg, "guardrail": "pii_blacklist"}), 400

        log_ai_query_generation(username=username, instruction=prompt, generated_sql=sql,
                                llm_provider=user_cfg.get("provider","?"),
                                llm_model=user_cfg.get("model","?"),
                                db_type=db_type, is_safe=True)
        body = {"sql": sql, "db_type": db_type}
        if pii_det.get("pii_warning"):
            body.update({"pii_warning": True, "pii_message": pii_msg})
        return jsonify(body), 200
    except Exception as exc:
        log_error(username, "sql_generation_error", str(exc), context=f"prompt={prompt[:100]}")
        return jsonify({"error": f"SQL generation failed: {exc}"}), 500
