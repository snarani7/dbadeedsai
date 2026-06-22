"""
app/api/logs.py — Activity log viewer endpoints (admin only).

Routes:
  GET /api/logs/files           → list available log files
  GET /api/logs/<logfile>       → paginated log entries (JSON)
  GET /api/logs/stats           → summary counts per log type
  DELETE /api/logs/<logfile>    → clear a log file (admin)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, UTC

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

logs_bp = Blueprint("logs", __name__)

LOG_FILES = {
    "activity":      "activity.log",
    "ai_chat":       "ai_chat.log",
    "sql":           "sql_execution.log",
    "login":         "login.log",
    "errors":        "errors.log",
    "page_views":    "page_views.log",
    "db_connections":"db_connections.log",
    "safety_blocks": "safety_blocks.log",
    "detailed":      "detailed_trace.log",
}


def _log_dir() -> Path:
    return Path(current_app.config.get("BASE_DIR", ".")) / "logs"


def _require_admin() -> tuple | None:
    if "user_management" not in get_jwt().get("permissions", []):
        return jsonify({"error": "Admin permission required"}), 403
    return None


def _parse_log_file(path: Path, limit: int = 200, offset: int = 0,
                    search: str = "") -> tuple[list[dict], int]:
    """Read JSONL log, return (entries, total_count)."""
    if not path.exists():
        return [], 0

    entries: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [], 0

    # Parse JSON lines, newest first
    parsed: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if search and search.lower() not in line.lower():
                continue
            parsed.append(obj)
        except Exception:
            parsed.append({"raw": line})

    total = len(parsed)
    return parsed[offset: offset + limit], total


# ── List log files ─────────────────────────────────────────────────────────────

@logs_bp.get("/files")
@jwt_required()
def list_log_files():
    if err := _require_admin():
        return err
    log_dir = _log_dir()
    result  = []
    for key, filename in LOG_FILES.items():
        path  = log_dir / filename
        size  = path.stat().st_size if path.exists() else 0
        lines = 0
        if path.exists():
            try:
                lines = sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
            except Exception:
                pass
        result.append({
            "key":      key,
            "filename": filename,
            "exists":   path.exists(),
            "size_kb":  round(size / 1024, 1),
            "entries":  lines,
        })
    return jsonify({"files": result}), 200


# ── Read a log file ────────────────────────────────────────────────────────────

@logs_bp.get("/<log_key>")
@jwt_required()
def read_log(log_key: str):
    if err := _require_admin():
        return err

    if log_key not in LOG_FILES:
        return jsonify({"error": f"Unknown log: {log_key}"}), 404

    limit  = min(int(request.args.get("limit",  200)), 1000)
    offset = int(request.args.get("offset", 0))
    search = request.args.get("search", "").strip()

    path = _log_dir() / LOG_FILES[log_key]
    entries, total = _parse_log_file(path, limit=limit, offset=offset, search=search)

    return jsonify({
        "log":     log_key,
        "entries": entries,
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "search":  search,
    }), 200


# ── Stats summary ──────────────────────────────────────────────────────────────

@logs_bp.get("/stats")
@jwt_required()
def log_stats():
    if err := _require_admin():
        return err

    log_dir = _log_dir()
    stats: dict[str, object] = {}
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    for key, filename in LOG_FILES.items():
        path = log_dir / filename
        if not path.exists():
            stats[key] = {"total": 0, "today": 0}
            continue
        total = 0
        today_count = 0
        try:
            for line in path.open(encoding="utf-8", errors="replace"):
                line = line.strip()
                if not line:
                    continue
                total += 1
                if today in line:
                    today_count += 1
        except Exception:
            pass
        stats[key] = {"total": total, "today": today_count}

    return jsonify({"stats": stats, "date": today}), 200


# ── Clear a log file ───────────────────────────────────────────────────────────

@logs_bp.delete("/<log_key>")
@jwt_required()
def clear_log(log_key: str):
    if err := _require_admin():
        return err

    if log_key not in LOG_FILES:
        return jsonify({"error": f"Unknown log: {log_key}"}), 404

    path = _log_dir() / LOG_FILES[log_key]
    if path.exists():
        path.write_text("", encoding="utf-8")

    from activity_logger import log_activity
    log_activity(get_jwt_identity(), "log_cleared", details=f"Cleared {log_key} log")

    return jsonify({"message": f"Log '{log_key}' cleared"}), 200
