"""
app/api/agents.py — AI Agent Scheduler & Email API

GET  /api/agents/schedules              → list all schedules
POST /api/agents/schedules              → create schedule
PUT  /api/agents/schedules/<id>         → update schedule
DEL  /api/agents/schedules/<id>         → delete schedule
POST /api/agents/schedules/<id>/toggle  → enable / disable
POST /api/agents/schedules/<id>/run     → trigger immediately

GET  /api/agents/runs                   → run history (all)
GET  /api/agents/runs/<schedule_id>     → run history for one schedule

GET  /api/agents/email-config           → SMTP settings (password masked)
POST /api/agents/email-config           → save SMTP settings
POST /api/agents/email-config/test      → send test email
POST /api/agents/email/send             → send one-off email with content
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

sys.path.insert(0, str(Path(__file__).parents[3]))

agents_bp = Blueprint("agents", __name__)


def _require_ai_agents():
    if "ai_agents" not in get_jwt().get("permissions", []):
        return jsonify({"error": "ai_agents permission required"}), 403


# ── Schedule CRUD ─────────────────────────────────────────────────────────────

@agents_bp.get("/schedules")
@jwt_required()
def list_schedules():
    if err := _require_ai_agents(): return err
    from agent_scheduler import list_schedules as _list
    return jsonify({"schedules": _list()}), 200


@agents_bp.post("/schedules")
@jwt_required()
def create_schedule():
    if err := _require_ai_agents(): return err
    username = get_jwt_identity()
    payload  = request.get_json(silent=True) or {}

    required = ["name", "agent_type", "task", "frequency"]
    missing  = [f for f in required if not payload.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    from agent_scheduler import create_schedule as _create
    schedule = _create(payload, created_by=username)
    return jsonify({"schedule": schedule, "message": "Schedule created"}), 201


@agents_bp.put("/schedules/<schedule_id>")
@jwt_required()
def update_schedule(schedule_id: str):
    if err := _require_ai_agents(): return err
    payload = request.get_json(silent=True) or {}
    from agent_scheduler import update_schedule as _update
    s = _update(schedule_id, payload)
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    return jsonify({"schedule": s, "message": "Schedule updated"}), 200


@agents_bp.delete("/schedules/<schedule_id>")
@jwt_required()
def delete_schedule(schedule_id: str):
    if err := _require_ai_agents(): return err
    from agent_scheduler import delete_schedule as _delete
    if not _delete(schedule_id):
        return jsonify({"error": "Schedule not found"}), 404
    return jsonify({"message": "Schedule deleted"}), 200


@agents_bp.post("/schedules/<schedule_id>/toggle")
@jwt_required()
def toggle_schedule(schedule_id: str):
    if err := _require_ai_agents(): return err
    from agent_scheduler import toggle_schedule as _toggle
    s = _toggle(schedule_id)
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    state = "enabled" if s["enabled"] else "disabled"
    return jsonify({"schedule": s, "message": f"Schedule {state}"}), 200


@agents_bp.post("/schedules/<schedule_id>/run")
@jwt_required()
def run_now(schedule_id: str):
    if err := _require_ai_agents(): return err
    username = get_jwt_identity()
    from agent_scheduler import run_agent_now
    run = run_agent_now(schedule_id, triggered_by=f"manual:{username}")
    if "error" in run:
        return jsonify(run), 404
    return jsonify({"run": run, "message": "Agent executed"}), 200


# ── Run history ───────────────────────────────────────────────────────────────

@agents_bp.get("/runs")
@jwt_required()
def get_all_runs():
    if err := _require_ai_agents(): return err
    limit = min(int(request.args.get("limit", 50)), 200)
    from agent_scheduler import get_run_history
    return jsonify({"runs": get_run_history(limit=limit)}), 200


@agents_bp.get("/runs/<schedule_id>")
@jwt_required()
def get_schedule_runs(schedule_id: str):
    if err := _require_ai_agents(): return err
    from agent_scheduler import get_run_history
    return jsonify({"runs": get_run_history(schedule_id=schedule_id)}), 200


# ── Email config ──────────────────────────────────────────────────────────────

@agents_bp.get("/email-config")
@jwt_required()
def get_email_config():
    if err := _require_ai_agents(): return err
    from agent_scheduler import get_email_config as _get
    cfg = dict(_get())
    # Mask password
    if cfg.get("smtp_password"):
        cfg["smtp_password"] = "••••••••"
    return jsonify({"config": cfg}), 200


@agents_bp.post("/email-config")
@jwt_required()
def save_email_config():
    if err := _require_ai_agents(): return err
    payload = request.get_json(silent=True) or {}
    cfg     = payload.get("config", payload)
    if not cfg:
        return jsonify({"error": "config body required"}), 400
    # Don't overwrite real password with masked placeholder
    if cfg.get("smtp_password") == "••••••••":
        from agent_scheduler import get_email_config as _get
        cfg["smtp_password"] = _get().get("smtp_password", "")
    from agent_scheduler import save_email_config as _save
    _save(cfg)
    return jsonify({"message": "Email config saved"}), 200


@agents_bp.post("/email-config/test")
@jwt_required()
def test_email():
    if err := _require_ai_agents(): return err
    from agent_scheduler import get_email_config, test_email_connection
    cfg     = get_email_config()
    ok, msg = test_email_connection(cfg)
    status  = 200 if ok else 400
    return jsonify({"ok": ok, "message": msg}), status


# ── One-off email send ────────────────────────────────────────────────────────

@agents_bp.post("/email/send")
@jwt_required()
def send_email_now():
    """Send agent output as email immediately (from the Run Agent tab Share button)."""
    if err := _require_ai_agents(): return err
    payload    = request.get_json(silent=True) or {}
    recipients = payload.get("to", "").strip()
    subject    = payload.get("subject", "Agent Report — dbadeeds.ai")
    content    = payload.get("content", "")

    if not recipients:
        return jsonify({"error": "Recipient email required"}), 400
    if not content:
        return jsonify({"error": "No content to send"}), 400

    from agent_scheduler import get_email_config, _send_email, _html_wrap
    cfg = get_email_config()
    if not cfg.get("smtp_host"):
        return jsonify({"error": "Email not configured — go to Schedules → Email Config tab"}), 400

    to_list = [e.strip() for e in recipients.split(",") if e.strip()]
    # Wrap content in styled HTML
    html = _html_wrap(subject, f"<div style='font-size:13px;line-height:1.8;color:#1e293b;white-space:pre-wrap'>{content}</div>")

    try:
        _send_email(cfg=cfg, to_addresses=to_list, subject=subject, html_body=html)
        return jsonify({"message": f"Report sent to {', '.join(to_list)}"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
