#!/usr/bin/env python3
"""
activity_logger.py — Comprehensive Activity Logger for Flask/dbadeeds.ai

Tracks: logins, SQL execution, AI chat, DB connections, LLM config changes,
safety blocks, errors, page views, feature usage.

Fully compatible with Flask (no Streamlit dependencies).
"""

from __future__ import annotations

import json
import os
import socket
import platform
import getpass
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# ── Log directory & files ──────────────────────────────────────────────────────
LOG_DIR          = Path(os.getenv("LOG_DIR", "logs"))
ACTIVITY_LOG     = LOG_DIR / "activity.log"
AI_CHAT_LOG      = LOG_DIR / "ai_chat.log"
SQL_LOG          = LOG_DIR / "sql_execution.log"
LOGIN_LOG        = LOG_DIR / "login.log"
ERROR_LOG        = LOG_DIR / "errors.log"
PAGE_VIEW_LOG    = LOG_DIR / "page_views.log"
DB_CONN_LOG      = LOG_DIR / "db_connections.log"
SAFETY_BLOCK_LOG = LOG_DIR / "safety_blocks.log"
DETAILED_LOG     = LOG_DIR / "detailed_trace.log"


def init_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _get_system_info() -> dict[str, str]:
    try:
        hostname = socket.gethostname()
        machine_ip = socket.gethostbyname(hostname)
    except Exception:
        hostname = machine_ip = "unknown"
    return {
        "hostname":       hostname,
        "machine_ip":     machine_ip,
        "os_name":        platform.system(),
        "os_release":     platform.release(),
        "python_version": platform.python_version(),
    }


def _get_client_ip() -> str:
    """Extract real client IP from Flask request context."""
    try:
        from flask import request as req
        for header in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP"):
            if ip := req.headers.get(header):
                first_ip = ip.split(",")[0].strip()
                if first_ip:
                    return first_ip
        return (req.environ.get("REMOTE_ADDR")
                or req.remote_addr
                or "unknown")
    except RuntimeError:
        return "server"
    except Exception:
        return "unknown"


def _get_user_agent() -> str:
    try:
        from flask import request as req
        return req.headers.get("User-Agent", "unknown")[:200]
    except Exception:
        return "unknown"


def _base_entry(username: str, activity_type: str) -> dict[str, Any]:
    init_logging()
    now  = datetime.now(UTC)
    sys_ = _get_system_info()
    return {
        "timestamp":      now.isoformat(timespec="seconds"),
        "date":           now.strftime("%Y-%m-%d"),
        "time":           now.strftime("%H:%M:%S"),
        "activity_type":  activity_type,
        "app_username":   username,
        "client_ip":      _get_client_ip(),
        "user_agent":     _get_user_agent(),
        **sys_,
    }


def _write(log_file: Path, entry: dict[str, Any]) -> None:
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        print(f"[activity_logger] write error → {log_file}: {exc}")


def _emit(log_file: Path, entry: dict[str, Any]) -> None:
    """Write to specific log + detailed trace."""
    _write(log_file, entry)
    _write(DETAILED_LOG, entry)


# ── Public API ─────────────────────────────────────────────────────────────────

def log_activity(username: str, activity: str, details: str = "",
                 success: bool = True, **kwargs: Any) -> None:
    e = _base_entry(username, activity)
    e.update({"details": details, "success": success, **kwargs})
    _emit(ACTIVITY_LOG, e)


def log_login(username: str, success: bool, reason: str = "") -> None:
    e = _base_entry(username, "login")
    e.update({"success": success, "reason": reason,
               "login_status": "SUCCESS" if success else "FAILED"})
    _emit(LOGIN_LOG, e)
    _write(ACTIVITY_LOG, e)


def log_logout(username: str) -> None:
    e = _base_entry(username, "logout")
    _emit(LOGIN_LOG, e)
    _write(ACTIVITY_LOG, e)


def log_page_view(username: str, page_name: str) -> None:
    e = _base_entry(username, "page_view")
    e.update({"page": page_name})
    _emit(PAGE_VIEW_LOG, e)


def log_sql_execution(username: str, sql: str, db_type: str,
                      execution_time: float | None = None,
                      rows_affected: int | None = None,
                      success: bool = True, error: str = "") -> None:
    safe_sql = re.sub(r"password\s*=\s*['\"][^'\"]*['\"]", "password=***",
                      sql[:500], flags=re.IGNORECASE)
    e = _base_entry(username, "sql_execution")
    e.update({"sql": safe_sql, "sql_length": len(sql), "db_type": db_type,
               "execution_time_ms": execution_time, "rows_affected": rows_affected,
               "success": success, "error": (error or "")[:200]})
    _emit(SQL_LOG, e)


def log_ai_chat(username: str, question: str, response: str,
                llm_provider: str = "unknown", llm_model: str = "unknown",
                db_type: str | None = None) -> None:
    e = _base_entry(username, "ai_chat")
    e.update({"question": question[:500], "question_length": len(question),
               "response": str(response)[:500], "response_length": len(str(response)),
               "llm_provider": llm_provider, "llm_model": llm_model,
               "db_type": db_type or "N/A"})
    _emit(AI_CHAT_LOG, e)



def log_ai_query_generation(username: str, instruction: str, generated_sql: str,
                             llm_provider: str, llm_model: str, db_type: str,
                             is_safe: bool = True) -> None:
    """Log AI-generated SQL query (from DB Explorer Generate SQL button)."""
    sanitized = generated_sql[:500] + "..." if len(generated_sql) > 500 else generated_sql
    e = _base_entry(username, "ai_query_generation")
    e.update({"instruction": instruction[:300], "generated_sql": sanitized,
               "sql_length": len(generated_sql), "llm_provider": llm_provider,
               "llm_model": llm_model, "db_type": db_type,
               "passed_safety": is_safe, "is_safe": is_safe})
    _emit(AI_CHAT_LOG, e)

def log_database_connection(username: str, connection_name: str, db_type: str,
                             action: str, success: bool = True, error: str = "") -> None:
    e = _base_entry(username, "database_connection")
    e.update({"connection_name": connection_name, "db_type": db_type,
               "action": action, "success": success, "error": (error or "")[:200]})
    _emit(DB_CONN_LOG, e)


def log_llm_config_change(username: str, old_provider: str, new_provider: str,
                           old_model: str, new_model: str) -> None:
    e = _base_entry(username, "llm_config_change")
    e.update({"old_provider": old_provider, "new_provider": new_provider,
               "old_model": old_model, "new_model": new_model})
    _emit(ACTIVITY_LOG, e)


def log_safety_block(username: str, sql: str, reason: str,
                     source: str = "sql_editor") -> None:
    e = _base_entry(username, "safety_block")
    e.update({"blocked_sql": sql[:300], "reason": reason,
               "source": source, "severity": "WARNING"})
    _emit(SAFETY_BLOCK_LOG, e)


def log_error(username: str, error_type: str, error_message: str,
              context: str = "", traceback: str = "") -> None:
    e = _base_entry(username, "error")
    e.update({"error_type": error_type, "error_message": error_message[:500],
               "context": context[:300], "traceback": (traceback or "")[:1000],
               "severity": "ERROR"})
    _emit(ERROR_LOG, e)


def log_feature_usage(username: str, feature: str, action: str,
                      details: str = "") -> None:
    e = _base_entry(username, "feature_usage")
    e.update({"feature": feature, "action": action, "details": details})
    _emit(ACTIVITY_LOG, e)


# Initialise on import
init_logging()
