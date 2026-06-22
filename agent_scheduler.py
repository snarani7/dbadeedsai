"""
agent_scheduler.py — Background scheduler for AI Agent tasks.

  • Stores schedules in data/agent_schedules.json
  • Runs agents on their cron-like interval using APScheduler
  • Sends results via SMTP email (config from data/email_config.json)
  • Fully thread-safe; designed to be started once in create_app()
"""
from __future__ import annotations

import json
import smtplib
import threading
import uuid
from datetime import datetime, UTC
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any


# ── File paths ────────────────────────────────────────────────────────────────
_BASE          = Path(__file__).parent
_SCHEDULES_FILE = _BASE / "data" / "agent_schedules.json"
_EMAIL_CFG_FILE = _BASE / "data" / "email_config.json"
_RUNS_FILE      = _BASE / "data" / "agent_run_history.json"
_LOCK           = threading.Lock()

# ── Default email config ──────────────────────────────────────────────────────
_DEFAULT_EMAIL_CFG: dict[str, Any] = {
    "smtp_host":     "",
    "smtp_port":     587,
    "smtp_user":     "",
    "smtp_password": "",
    "use_tls":       True,
    "from_address":  "",
    "from_name":     "dbadeeds.ai Agent",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Low-level JSON helpers
# ══════════════════════════════════════════════════════════════════════════════

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Email config management
# ══════════════════════════════════════════════════════════════════════════════

def get_email_config() -> dict[str, Any]:
    cfg = _read_json(_EMAIL_CFG_FILE, {})
    return {**_DEFAULT_EMAIL_CFG, **cfg}


def save_email_config(cfg: dict[str, Any]) -> None:
    # Never persist empty → merge with existing
    existing = get_email_config()
    merged   = {**existing, **{k: v for k, v in cfg.items() if v != ""}}
    _write_json(_EMAIL_CFG_FILE, merged)


def test_email_connection(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Send a test email; return (ok, message)."""
    try:
        _send_email(
            cfg=cfg,
            to_addresses=[cfg["smtp_user"]],
            subject="✅ dbadeeds.ai — Email Connection Test",
            html_body=_html_wrap(
                "Email Configuration Test",
                "<p>Your SMTP settings are working correctly.</p>"
                "<p>This test was sent from <strong>dbadeeds.ai</strong>.</p>"
            ),
        )
        return True, "Test email sent successfully"
    except Exception as exc:
        return False, str(exc)


# ══════════════════════════════════════════════════════════════════════════════
#  Schedule CRUD
# ══════════════════════════════════════════════════════════════════════════════

def list_schedules() -> list[dict]:
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
    return sorted(data.values(), key=lambda s: s.get("created_at", ""), reverse=True)


def get_schedule(schedule_id: str) -> dict | None:
    with _LOCK:
        return _read_json(_SCHEDULES_FILE, {}).get(schedule_id)


def create_schedule(payload: dict, created_by: str) -> dict:
    sid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat(timespec="seconds")
    schedule = {
        "id":          sid,
        "name":          payload["name"],
        "agent_type":    payload["agent_type"],
        "db_type":       payload.get("db_type", "postgres"),
        "connection_id": payload.get("connection_id", ""),   # which DB connection to run against
        "template_name": payload.get("template_name", ""),   # agent template name (optional override)
        "task":          payload["task"],
        "frequency":   payload["frequency"],        # hourly | daily | weekly
        "hour":        int(payload.get("hour", 8)),  # 0-23
        "minute":      int(payload.get("minute", 0)),
        "day_of_week": payload.get("day_of_week", "mon"),  # mon-sun (weekly only)
        "email_to":    payload.get("email_to", ""),        # comma-separated
        "email_subject": payload.get("email_subject", f"Agent Report: {payload['name']}"),
        "enabled":     True,
        "created_at":  now,
        "created_by":  created_by,
        "last_run":    None,
        "last_status": None,
        "run_count":   0,
    }
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
        data[sid] = schedule
        _write_json(_SCHEDULES_FILE, data)
    _register_job(schedule)
    return schedule


def update_schedule(schedule_id: str, payload: dict) -> dict | None:
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
        if schedule_id not in data:
            return None
        s = data[schedule_id]
        for k in ("name", "task", "frequency", "hour", "minute",
                  "day_of_week", "email_to", "email_subject", "enabled",
                  "connection_id", "template_name"):
            if k in payload:
                s[k] = payload[k]
        s["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        data[schedule_id] = s
        _write_json(_SCHEDULES_FILE, data)
    _register_job(s)
    return s


def delete_schedule(schedule_id: str) -> bool:
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
        if schedule_id not in data:
            return False
        del data[schedule_id]
        _write_json(_SCHEDULES_FILE, data)
    _remove_job(schedule_id)
    return True


def toggle_schedule(schedule_id: str) -> dict | None:
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
        if schedule_id not in data:
            return None
        data[schedule_id]["enabled"] = not data[schedule_id]["enabled"]
        _write_json(_SCHEDULES_FILE, data)
    s = data[schedule_id]
    if s["enabled"]:
        _register_job(s)
    else:
        _remove_job(schedule_id)
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  Run history
# ══════════════════════════════════════════════════════════════════════════════

def get_run_history(schedule_id: str | None = None, limit: int = 50) -> list[dict]:
    with _LOCK:
        runs = _read_json(_RUNS_FILE, [])
    if schedule_id:
        runs = [r for r in runs if r.get("schedule_id") == schedule_id]
    return sorted(runs, key=lambda r: r.get("started_at", ""), reverse=True)[:limit]


def _save_run(run: dict) -> None:
    with _LOCK:
        runs = _read_json(_RUNS_FILE, [])
        runs.append(run)
        # Keep only last 500 runs
        runs = sorted(runs, key=lambda r: r.get("started_at", ""), reverse=True)[:500]
        _write_json(_RUNS_FILE, runs)


# ══════════════════════════════════════════════════════════════════════════════
#  Agent execution (runs inside APScheduler thread)
# ══════════════════════════════════════════════════════════════════════════════

def run_agent_now(schedule_id: str, triggered_by: str = "scheduler") -> dict:
    """Execute an agent and email results. Returns run record."""
    schedule = get_schedule(schedule_id)
    if not schedule:
        return {"error": "Schedule not found"}

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    run = {
        "id":           str(uuid.uuid4()),
        "schedule_id":  schedule_id,
        "schedule_name": schedule["name"],
        "triggered_by": triggered_by,
        "started_at":   started_at,
        "status":       "running",
        "output":       "",
        "email_sent":   False,
        "error":        None,
    }

    try:
        output = _execute_agent(schedule)
        run["output"]     = output
        run["status"]     = "success"
        run["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")

        # Email results
        if schedule.get("email_to", "").strip():
            email_ok, email_msg = _send_agent_report(schedule, output, started_at)
            run["email_sent"]    = email_ok
            run["email_message"] = email_msg
        else:
            run["email_sent"]    = False
            run["email_message"] = "No recipients configured"

    except Exception as exc:
        run["status"]     = "failed"
        run["error"]      = str(exc)
        run["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    # Persist run
    _save_run(run)

    # Update schedule last_run stats
    with _LOCK:
        data = _read_json(_SCHEDULES_FILE, {})
        if schedule_id in data:
            data[schedule_id]["last_run"]    = started_at
            data[schedule_id]["last_status"] = run["status"]
            data[schedule_id]["run_count"]   = data[schedule_id].get("run_count", 0) + 1
            _write_json(_SCHEDULES_FILE, data)

    return run


def _activate_connection(connection_id: str, db_type: str) -> str | None:
    """
    Temporarily activate a specific connection for the scheduler run.
    Returns error string if activation fails, None on success.
    """
    if not connection_id:
        return None   # use whatever is already active
    try:
        f = _BASE / "data" / "db_connections.json"
        if not f.exists():
            return "db_connections.json not found"
        conns = json.loads(f.read_text(encoding="utf-8"))
        if connection_id not in conns:
            return f"Connection '{connection_id}' not found"
        # Deactivate all of same db_type, activate the chosen one
        for cid, conn in conns.items():
            if conn.get("db_type") == db_type:
                conn["is_active"] = (cid == connection_id)
        f.write_text(json.dumps(conns, indent=2), encoding="utf-8")
        return None
    except Exception as e:
        return str(e)


def _execute_agent(schedule: dict) -> str:
    """Run the LangChain REACT agent with real DB tools. Returns text output."""
    from langchain.agents import initialize_agent, AgentType
    from app.api.llm_settings import build_llm, _get_user_cfg
    from agent_executor_tools import build_agent_tools, get_system_prompt

    db_type       = schedule.get("db_type", "postgres")
    agent_type    = schedule.get("agent_type", "performance")
    task          = schedule.get("task", "Analyse database performance")
    connection_id = schedule.get("connection_id", "")
    template_name = schedule.get("template_name", "")

    # Activate the specific connection this schedule targets
    if connection_id:
        err = _activate_connection(connection_id, db_type)
        if err:
            return f"Connection error: {err}. Cannot run agent."

    # If a template name is given, use its system prompt
    if template_name:
        try:
            from agent_executor_tools import AgentTemplates
            matches = [t for t in AgentTemplates.get_all_templates() if t.name == template_name]
            if matches:
                t = matches[0]
                db_type    = t.database_type.value
                agent_type = t.agent_type.value
                # Use template system prompt but keep the user's custom task
                system_override = t.system_prompt
            else:
                system_override = None
        except Exception:
            system_override = None
    else:
        system_override = None

    cfg  = _get_user_cfg("admin")
    llm  = build_llm(cfg, streaming=False)

    tools_map   = build_agent_tools("scheduler")
    tool_name   = "OracleQueryAgent" if db_type == "oracle" else "PostgresQueryAgent"
    agent_tools = [tools_map[tool_name]]
    system      = system_override if system_override else get_system_prompt(agent_type, db_type)

    is_ollama = "ollama" in str(type(llm)).lower()
    agent_executor = initialize_agent(
        agent_tools, llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=False,
        max_iterations=20 if is_ollama else 10,
        handle_parsing_errors=True,
        early_stopping_method="generate",
        agent_kwargs={"prefix": system},
    )
    return agent_executor.run(task)


# ══════════════════════════════════════════════════════════════════════════════
#  Email delivery
# ══════════════════════════════════════════════════════════════════════════════

def _send_agent_report(schedule: dict, output: str, ran_at: str) -> tuple[bool, str]:
    """
    Send agent results via the notification system (all enabled channels).
    Falls back to legacy SMTP if notifications module not available.
    """
    subject   = schedule.get("email_subject") or f"Agent Report: {schedule['name']}"
    recipients = schedule.get("email_to", "")
    level      = "WARNING" if _looks_like_problem(output) else "INFO"

    # Try new multi-channel notification system first
    try:
        from app.api.notifications import send_notification, should_notify_agent_result
        if not should_notify_agent_result(output, "success"):
            return False, "Alert rules: no notification needed"
        results = send_notification(
            title=subject, message=output, level=level,
            source=f"agent_scheduler:{schedule['name']}",
            recipients=recipients,
        )
        if results:
            ok_ch  = [ch for ch,(ok,_) in results.items() if ok]
            fail_ch = [f"{ch}: {msg}" for ch,(ok,msg) in results.items() if not ok]
            return bool(ok_ch), f"Sent via: {', '.join(ok_ch)}" + (f" | Failed: {'; '.join(fail_ch)}" if fail_ch else "")
        return False, "No notification channels enabled"
    except ImportError:
        pass

    # Legacy SMTP fallback
    cfg = get_email_config()
    if not cfg.get("smtp_host"):
        return False, "Email not configured"
    rcpts = [e.strip() for e in recipients.split(",") if e.strip()]
    if not rcpts:
        return False, "No recipients"
    try:
        _send_email(cfg=cfg, to_addresses=rcpts, subject=subject,
                    html_body=_build_report_html(schedule, output, ran_at))
        return True, f"Email sent to {', '.join(rcpts)}"
    except Exception as exc:
        return False, str(exc)


def _looks_like_problem(output: str) -> bool:
    """Quick scan of agent output to determine severity."""
    import re
    keywords = ["blocking","deadlock","lag","full","ORA-","FATAL","ERROR",
                "slow quer","high cpu","memory pressure","out of space"]
    out_lower = output.lower()
    return any(re.search(kw.lower(), out_lower) for kw in keywords)


def _send_email(cfg: dict, to_addresses: list[str],
                subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{cfg.get('from_name','dbadeeds.ai')} <{cfg['from_address'] or cfg['smtp_user']}>"
    msg["To"]      = ", ".join(to_addresses)
    msg.attach(MIMEText(html_body, "html"))

    port = int(cfg.get("smtp_port", 587))
    if cfg.get("use_tls", True):
        server = smtplib.SMTP(cfg["smtp_host"], port, timeout=15)
        server.ehlo()
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(cfg["smtp_host"], port, timeout=15)

    if cfg.get("smtp_user") and cfg.get("smtp_password"):
        server.login(cfg["smtp_user"], cfg["smtp_password"])

    server.sendmail(msg["From"], to_addresses, msg.as_string())
    server.quit()


def _build_report_html(schedule: dict, output: str, ran_at: str) -> str:
    """Build a clean HTML email report from agent output."""
    # Convert markdown-ish output to simple HTML
    import re
    html_output = output
    # Bold **text**
    html_output = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_output)
    # Code blocks
    html_output = re.sub(r'```[\w]*\n?(.*?)```', r'<pre style="background:#f1f5f9;padding:12px;border-radius:6px;font-family:monospace;font-size:12px;overflow:auto">\1</pre>', html_output, flags=re.DOTALL)
    # Headings
    html_output = re.sub(r'^### (.+)$', r'<h3 style="color:#1e3a5f;font-size:14px;margin:16px 0 6px">\1</h3>', html_output, flags=re.MULTILINE)
    html_output = re.sub(r'^## (.+)$',  r'<h2 style="color:#1e3a5f;font-size:16px;margin:20px 0 8px">\1</h2>', html_output, flags=re.MULTILINE)
    # Bullet points
    html_output = re.sub(r'^[-•] (.+)$', r'<li style="margin:4px 0">\1</li>', html_output, flags=re.MULTILINE)
    # Newlines to <br>
    html_output = html_output.replace('\n', '<br>')

    freq_label = {"hourly": "Every Hour", "daily": "Daily", "weekly": "Weekly"}.get(schedule.get("frequency", ""), schedule.get("frequency", ""))
    db_badge_color = "#f59e0b" if schedule.get("db_type") == "oracle" else "#3b82f6"

    content = f"""
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;width:130px">Agent Type</td>
        <td style="padding:6px 0;font-size:12px;color:#1e293b">{schedule.get('agent_type','').title()}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600">Database</td>
        <td style="padding:6px 0">
          <span style="background:{db_badge_color};color:#fff;font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600">
            {schedule.get('db_type','').upper()}
          </span>
        </td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600">Schedule</td>
        <td style="padding:6px 0;font-size:12px;color:#1e293b">{freq_label}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600">Run At</td>
        <td style="padding:6px 0;font-size:12px;color:#1e293b">{ran_at.replace('T',' ').replace('+00:00',' UTC')}</td>
      </tr>
      <tr>
        <td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600">Task</td>
        <td style="padding:6px 0;font-size:12px;color:#1e293b">{schedule.get('task','')[:200]}</td>
      </tr>
    </table>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0"/>
    <div style="font-size:13px;line-height:1.8;color:#1e293b">{html_output}</div>
    """
    return _html_wrap(f"Agent Report: {schedule['name']}", content)


def _html_wrap(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table style="width:100%;max-width:680px;margin:30px auto">
    <tr>
      <td>
        <!-- Header -->
        <div style="background:linear-gradient(135deg,#1e3a5f,#0369a1);border-radius:12px 12px 0 0;padding:28px 32px">
          <div style="color:#fff;font-size:22px;font-weight:700">🧠 dbadeeds.ai</div>
          <div style="color:#bae6fd;font-size:14px;margin-top:4px">{title}</div>
        </div>
        <!-- Body -->
        <div style="background:#fff;border:1px solid #e2e8f0;border-top:none;padding:28px 32px">
          {content}
        </div>
        <!-- Footer -->
        <div style="background:#f1f5f9;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 12px 12px;
             padding:16px 32px;text-align:center">
          <div style="font-size:11px;color:#94a3b8">
            Sent by <strong>dbadeeds.ai</strong> AI Agent Scheduler · 
            <a href="#" style="color:#0369a1;text-decoration:none">Manage Schedules</a>
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  APScheduler integration
# ══════════════════════════════════════════════════════════════════════════════

_scheduler = None


def start_scheduler(app) -> None:
    """Start APScheduler and register all enabled schedules. Call once in create_app()."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        app.logger.warning("APScheduler not installed — agent scheduling disabled. Run: pip install apscheduler")
        return

    _scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
    _scheduler.start()

    # Register all enabled schedules
    for s in list_schedules():
        if s.get("enabled"):
            _register_job(s)

    app.logger.info("Agent scheduler started")


def _register_job(schedule: dict) -> None:
    global _scheduler
    if not _scheduler:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return

    sid     = schedule["id"]
    freq    = schedule.get("frequency", "daily")
    hour    = schedule.get("hour", 8)
    minute  = schedule.get("minute", 0)
    dow     = schedule.get("day_of_week", "mon")

    # Remove old job if exists
    _remove_job(sid)

    if not schedule.get("enabled", True):
        return

    if freq == "hourly":
        trigger = CronTrigger(minute=minute)
    elif freq == "weekly":
        trigger = CronTrigger(day_of_week=dow, hour=hour, minute=minute)
    else:  # daily
        trigger = CronTrigger(hour=hour, minute=minute)

    _scheduler.add_job(
        func=run_agent_now,
        trigger=trigger,
        args=[sid, "scheduler"],
        id=f"agent_{sid}",
        replace_existing=True,
        misfire_grace_time=300,
    )


def _remove_job(schedule_id: str) -> None:
    global _scheduler
    if not _scheduler:
        return
    job_id = f"agent_{schedule_id}"
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass
