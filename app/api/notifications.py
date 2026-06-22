"""
app/api/notifications.py — Notification channel configuration API.

Supports: SMTP email · Microsoft Teams webhook · Generic webhook · Slack (for future MCP integration)

Data stored in: data/notification_config.json
Routes:
  GET/POST /api/notifications/config           → get / save full config
  POST     /api/notifications/test/<channel>   → test a channel
  GET      /api/notifications/channels         → list configured channels
  POST     /api/notifications/send             → manual send (admin)
"""
from __future__ import annotations

import json
import smtplib
import threading
from datetime import datetime, UTC
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

notifications_bp = Blueprint("notifications", __name__)
_LOCK = threading.Lock()

_DEFAULT_CFG: dict[str, Any] = {
    "email": {
        "enabled":       False,
        "smtp_host":     "",
        "smtp_port":     587,
        "smtp_user":     "",
        "smtp_password": "",
        "use_tls":       True,
        "from_address":  "",
        "from_name":     "dbadeeds.ai",
        "default_recipients": "",
    },
    "teams": {
        "enabled":      False,
        "webhook_url":  "",
        "channel_name": "",
    },
    "slack": {
        "enabled":     False,
        "webhook_url": "",
        "channel":     "#dba-alerts",
    },
    "bmc_proactive": {
        "enabled":      False,
        "server_url":   "",
        "api_key":      "",
        "cell_name":    "",
        "severity_map": {
            "CRITICAL": "CRITICAL",
            "WARNING":  "MAJOR",
            "INFO":     "MINOR",
        },
    },
    "webhook": {
        "enabled":     False,
        "url":         "",
        "method":      "POST",
        "headers":     {},
        "secret":      "",
    },
    "alert_rules": {
        "notify_on_agent_error":    True,
        "notify_on_agent_success":  False,
        "notify_on_problem_found":  True,
        "problem_keywords": [
            "blocking", "locked", "deadlock", "replication lag",
            "tablespace.*full", "out of space", "ORA-", "FATAL",
            "ERROR", "slow quer", "high cpu", "memory pressure"
        ],
    }
}


# ── helpers ────────────────────────────────────────────────────────────────────

def _cfg_file() -> Path:
    try:
        from flask import current_app
        base = current_app.config.get("BASE_DIR", ".")
    except Exception:
        base = "."
    return Path(base) / "data" / "notification_config.json"


def _load() -> dict:
    f = _cfg_file()
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
            # Deep merge with defaults
            merged = json.loads(json.dumps(_DEFAULT_CFG))
            for k, v in saved.items():
                if isinstance(v, dict) and k in merged:
                    merged[k].update(v)
                else:
                    merged[k] = v
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(_DEFAULT_CFG))


def _save(cfg: dict) -> None:
    f = _cfg_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _require_admin():
    if "user_management" not in get_jwt().get("permissions", []):
        return jsonify({"error": "Admin permission required"}), 403


# ── routes ─────────────────────────────────────────────────────────────────────

@notifications_bp.get("/config")
@jwt_required()
def get_config():
    if err := _require_admin(): return err
    cfg = _load()
    # Mask passwords in response
    safe = json.loads(json.dumps(cfg))
    if safe["email"].get("smtp_password"):
        safe["email"]["smtp_password"] = "••••••••"
    if safe["bmc_proactive"].get("api_key"):
        safe["bmc_proactive"]["api_key"] = "••••••••"
    if safe["webhook"].get("secret"):
        safe["webhook"]["secret"] = "••••••••"
    return jsonify(safe), 200


@notifications_bp.post("/config")
@jwt_required()
def save_config():
    if err := _require_admin(): return err
    data = request.get_json(silent=True) or {}
    cfg  = _load()
    for channel in ("email","teams","slack","webhook","alert_rules"):
        if channel in data:
            # Don't overwrite masked passwords
            updates = data[channel]
            if isinstance(updates, dict):
                for k, v in updates.items():
                    if v not in ("••••••••",) and v != "":
                        cfg[channel][k] = v
                    elif v == "":
                        cfg[channel][k] = v
    _save(cfg)
    return jsonify({"ok": True, "message": "Notification settings saved"}), 200


@notifications_bp.get("/channels")
@jwt_required()
def list_channels():
    if err := _require_admin(): return err
    cfg = _load()
    channels = []
    icons = {"email":"📧","teams":"💼","slack":"💬","webhook":"🔗"}
    for name, conf in cfg.items():
        if name == "alert_rules": continue
        channels.append({
            "id":      name,
            "label":   name.replace("_"," ").title(),
            "icon":    icons.get(name,"🔔"),
            "enabled": conf.get("enabled", False),
            "configured": _is_configured(name, conf),
        })
    return jsonify({"channels": channels}), 200


def _is_configured(name: str, conf: dict) -> bool:
    if name == "email":
        return bool(conf.get("smtp_host") and conf.get("smtp_user"))
    if name == "teams":
        return bool(conf.get("webhook_url"))
    if name == "slack":
        return bool(conf.get("webhook_url"))
    if name == "webhook":
        return bool(conf.get("url"))
    return False


@notifications_bp.post("/test/<channel>")
@jwt_required()
def test_channel(channel: str):
    if err := _require_admin(): return err
    cfg  = _load()
    body = request.get_json(silent=True) or {}
    # Allow overriding config with form values for the test
    test_cfg = {**cfg.get(channel, {}), **{k:v for k,v in body.items() if v and v != "••••••••"}}

    ok, msg = _dispatch_test(channel, test_cfg)
    return jsonify({"ok": ok, "message": msg}), 200 if ok else 400


def _dispatch_test(channel: str, conf: dict) -> tuple[bool, str]:
    test_payload = {
        "title":   "dbadeeds.ai — Notification Test",
        "message": "This is a test notification from dbadeeds.ai. Your configuration is working correctly.",
        "level":   "INFO",
        "source":  "notification_test",
    }
    try:
        if channel == "email":    return _send_email_notification(conf, test_payload)
        if channel == "teams":    return _send_teams_notification(conf, test_payload)
        if channel == "slack":    return _send_slack_notification(conf, test_payload)
        if channel == "webhook":  return _send_webhook_notification(conf, test_payload)
        return False, f"Unknown channel: {channel}"
    except Exception as e:
        return False, str(e)


# ── public dispatch (called by agent_scheduler) ────────────────────────────────

def send_notification(title: str, message: str, level: str = "INFO",
                      source: str = "agent_scheduler",
                      recipients: str = "") -> dict[str, Any]:
    """
    Dispatch a notification to all enabled channels.
    Returns dict of channel→(ok, message) results.
    """
    cfg     = _load()
    payload = {"title": title, "message": message, "level": level, "source": source}
    results = {}

    if cfg["email"]["enabled"] and _is_configured("email", cfg["email"]):
        to = recipients or cfg["email"].get("default_recipients", "")
        cfg["email"]["_override_recipients"] = to
        results["email"] = _send_email_notification(cfg["email"], payload)

    if cfg["teams"]["enabled"] and _is_configured("teams", cfg["teams"]):
        results["teams"] = _send_teams_notification(cfg["teams"], payload)

    if cfg["slack"]["enabled"] and _is_configured("slack", cfg["slack"]):
        results["slack"] = _send_slack_notification(cfg["slack"], payload)

    if cfg["webhook"]["enabled"] and _is_configured("webhook", cfg["webhook"]):
        results["webhook"] = _send_webhook_notification(cfg["webhook"], payload)

    return results


def should_notify_agent_result(output: str, status: str) -> bool:
    """Check agent output against alert rules to decide if notification should fire."""
    import re
    cfg   = _load()
    rules = cfg.get("alert_rules", {})

    if status == "failed" and rules.get("notify_on_agent_error", True):
        return True
    if status == "success" and rules.get("notify_on_agent_success", False):
        return True
    if status == "success" and rules.get("notify_on_problem_found", True):
        keywords = rules.get("problem_keywords", [])
        out_lower = output.lower()
        for kw in keywords:
            if re.search(kw.lower(), out_lower):
                return True
    return False


# ── channel implementations ────────────────────────────────────────────────────

def _send_email_notification(conf: dict, payload: dict) -> tuple[bool, str]:
    if not conf.get("smtp_host"):
        return False, "SMTP host not configured"
    recipients_raw = conf.get("_override_recipients") or conf.get("default_recipients", "")
    recipients = [e.strip() for e in recipients_raw.split(",") if e.strip()]
    if not recipients:
        recipients = [conf["smtp_user"]]  # fall back to sender

    level_emoji = {"CRITICAL":"🔴","WARNING":"🟡","INFO":"🟢","ERROR":"🔴"}.get(payload["level"],"🔔")
    subject = f"{level_emoji} {payload['title']}"

    html = f"""<!DOCTYPE html><html><body style="font-family:-apple-system,sans-serif;background:#f8fafc;padding:20px">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden">
  <div style="background:#0F1E35;padding:20px 28px">
    <div style="color:#fff;font-size:18px;font-weight:700">🤖 dbadeeds.ai</div>
    <div style="color:#94A3B8;font-size:13px;margin-top:4px">{payload['title']}</div>
  </div>
  <div style="padding:24px 28px">
    <div style="display:inline-block;background:{'#FEE2E2' if payload['level'] in ('CRITICAL','ERROR') else '#FEF3C7' if payload['level']=='WARNING' else '#DCFCE7'};
      color:{'#991B1B' if payload['level'] in ('CRITICAL','ERROR') else '#92400E' if payload['level']=='WARNING' else '#166534'};
      font-size:11px;font-weight:700;padding:3px 10px;border-radius:12px;margin-bottom:16px">{payload['level']}</div>
    <div style="font-size:14px;line-height:1.7;color:#1E293B;white-space:pre-wrap">{payload['message'][:3000]}</div>
    <div style="margin-top:20px;padding-top:16px;border-top:1px solid #F1F5F9;font-size:11px;color:#94A3B8">
      Sent by dbadeeds.ai · Source: {payload['source']} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}
    </div>
  </div>
</div></body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{conf.get('from_name','dbadeeds.ai')} <{conf.get('from_address') or conf['smtp_user']}>"
        msg["To"]      = ", ".join(recipients)
        msg.attach(MIMEText(html, "html"))

        port = int(conf.get("smtp_port", 587))
        if conf.get("use_tls", True):
            srv = smtplib.SMTP(conf["smtp_host"], port, timeout=15)
            srv.ehlo(); srv.starttls()
        else:
            srv = smtplib.SMTP_SSL(conf["smtp_host"], port, timeout=15)

        if conf.get("smtp_user") and conf.get("smtp_password"):
            srv.login(conf["smtp_user"], conf["smtp_password"])

        srv.sendmail(msg["From"], recipients, msg.as_string())
        srv.quit()
        return True, f"Email sent to {', '.join(recipients)}"
    except Exception as e:
        return False, str(e)


def _send_teams_notification(conf: dict, payload: dict) -> tuple[bool, str]:
    """Send Adaptive Card to MS Teams via incoming webhook."""
    if not conf.get("webhook_url"):
        return False, "Teams webhook URL not configured"

    level_color = {
        "CRITICAL": "attention", "ERROR": "attention",
        "WARNING":  "warning",   "INFO":  "good"
    }.get(payload["level"], "accent")

    body = {
        "type":        "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type":    "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type":  "TextBlock",
                        "text":  f"🤖 dbadeeds.ai — {payload['title']}",
                        "size":  "Medium",
                        "weight":"Bolder",
                        "color": level_color,
                    },
                    {
                        "type":    "FactSet",
                        "facts":   [
                            {"title": "Level",  "value": payload["level"]},
                            {"title": "Source", "value": payload["source"]},
                            {"title": "Time",   "value": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")},
                        ]
                    },
                    {
                        "type": "TextBlock",
                        "text": payload["message"][:1000],
                        "wrap": True,
                        "size": "Small",
                    },
                ]
            }
        }]
    }
    try:
        r = requests.post(conf["webhook_url"], json=body, timeout=10)
        if r.status_code in (200, 202):
            return True, f"Teams notification sent to {conf.get('channel_name','webhook')}"
        return False, f"Teams returned HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_slack_notification(conf: dict, payload: dict) -> tuple[bool, str]:
    """Send Block Kit message to Slack via incoming webhook."""
    if not conf.get("webhook_url"):
        return False, "Slack webhook URL not configured"

    emoji = {"CRITICAL":"🔴","ERROR":"🔴","WARNING":"🟡","INFO":"🟢"}.get(payload["level"],"🔔")
    body = {
        "blocks": [
            {
                "type": "header",
                "text": {"type":"plain_text","text": f"🤖 dbadeeds.ai Alert","emoji": True}
            },
            {
                "type":   "section",
                "fields": [
                    {"type":"mrkdwn","text": f"*{emoji} Level:*\n{payload['level']}"},
                    {"type":"mrkdwn","text": f"*Source:*\n{payload['source']}"},
                    {"type":"mrkdwn","text": f"*Title:*\n{payload['title']}"},
                    {"type":"mrkdwn","text": f"*Time:*\n{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"},
                ]
            },
            {
                "type": "section",
                "text": {"type":"mrkdwn","text": payload["message"][:2000]}
            },
            {"type":"divider"},
        ]
    }
    try:
        r = requests.post(conf["webhook_url"], json=body, timeout=10)
        if r.status_code == 200 and r.text == "ok":
            return True, f"Slack message sent to {conf.get('channel','#alerts')}"
        return False, f"Slack returned {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def _send_webhook_notification(conf: dict, payload: dict) -> tuple[bool, str]:
    """POST/GET to a generic webhook URL."""
    if not conf.get("url"):
        return False, "Webhook URL not configured"

    headers = {
        "Content-Type": "application/json",
        **conf.get("headers", {})
    }
    if conf.get("secret"):
        headers["X-Webhook-Secret"] = conf["secret"]

    body = {
        "title":    payload["title"],
        "message":  payload["message"],
        "level":    payload["level"],
        "source":   payload["source"],
        "platform": "dbadeeds.ai",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        method = conf.get("method", "POST").upper()
        fn = requests.post if method == "POST" else requests.get
        r  = fn(conf["url"], json=body, headers=headers, timeout=10)
        if r.status_code < 400:
            return True, f"Webhook responded {r.status_code}"
        return False, f"Webhook returned {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)
