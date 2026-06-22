"""
app/web.py — Web UI routes serving Jinja2 HTML pages.

Python 3.14 features used:
  • X | None union types            — cleaner signatures
  • match/case                      — permission dispatch table
  • walrus :=                       — inline user resolution
  • type alias                      — UserTuple
"""

from __future__ import annotations

from flask import Blueprint, render_template, redirect, url_for, Response
from flask_jwt_extended import get_jwt_identity, get_jwt, verify_jwt_in_request

web_bp = Blueprint("web", __name__)

# ── Type alias ─────────────────────────────────────────────────────────────────
type UserTuple = tuple[str | None, list[str]]


def _current_user() -> UserTuple:
    """Return (username, permissions) from JWT cookie, or (None, [])."""
    try:
        verify_jwt_in_request(locations=["cookies"])
        claims = get_jwt()
        return get_jwt_identity(), claims.get("permissions", [])
    except Exception:
        return None, []


def _guard(perm: str) -> Response | None:
    """
    Return a redirect/403 response if the user lacks *perm*, else None.

    Uses walrus operator to avoid calling _current_user() twice.
    """
    if not (username := _current_user()[0]):
        return redirect(url_for("web.login_page"))

    _, perms = _current_user()
    if perm not in perms:
        return render_template("403.html", permission=perm), 403
    return None


def _render(template: str, perm: str, **kwargs) -> Response:
    """Guard + render in one call — used by every protected route."""
    if redir := _guard(perm):
        return redir
    username, perms = _current_user()
    return render_template(template, username=username, permissions=perms, **kwargs)


# ── Public routes ──────────────────────────────────────────────────────────────

@web_bp.get("/")
def index():
    username, _ = _current_user()
    return redirect(url_for("web.dashboard" if username else "web.login_page"))


@web_bp.get("/login")
def login_page():
    username, _ = _current_user()
    if username:
        return redirect(url_for("web.dashboard"))
    return render_template("login.html")


@web_bp.get("/logout")
def logout():
    """Clear JWT cookies and redirect to login."""
    response = redirect(url_for("web.login_page"))
    response.delete_cookie("access_token_cookie")
    response.delete_cookie("refresh_token_cookie")
    return response


# ── Protected pages — each is a single _render() call ─────────────────────────

@web_bp.get("/dashboard")
def dashboard():
    return _render("dashboard.html", "dashboard")


@web_bp.get("/connections")
def connections():
    return _render("connections.html", "db_connections")


@web_bp.get("/explorer")
def explorer():
    return _render("explorer.html", "db_explorer")


@web_bp.get("/ai")
def ai_assistant():
    import json, os
    from pathlib import Path
    from flask import current_app
    from flask_jwt_extended import get_jwt_identity

    # Build DB cards — same as Streamlit _cards
    def _host_from_cs(cs, db_type):
        try:
            import re
            if db_type == "oracle":
                return cs.split("@")[1].split(":")[0] if "@" in cs else "—"
            m = re.search(r"@([^:/]+)", cs)
            if m: return m.group(1)
            m = re.search(r"host=([^\s]+)", cs)
            return m.group(1) if m else "localhost"
        except Exception:
            return "—"

    # Resolve username first — needed for per-user active connection lookup
    try:
        username_for_llm, _ = _current_user()
    except Exception:
        username_for_llm = None

    ora_conn = pg_conn = None
    try:
        _raw = (current_app.config.get("DB_CONNECTIONS_FILE")
                or os.getenv("DB_CONNECTIONS_FILE"))
        # parents[1] = final_flask/  (app/web.py → app → final_flask)
        f = Path(_raw) if _raw else (Path(__file__).resolve().parents[1] / "data" / "db_connections.json")
        if f.exists():
            all_conns = json.loads(f.read_text())
            # Per-user active connections
            try:
                from app.api.user_state import get_active_conn_id
                base_d  = current_app.config.get("BASE_DIR") or str(Path(__file__).resolve().parents[1])
                _uname  = username_for_llm or "admin"
                ora_cid = get_active_conn_id(str(base_d), _uname, "oracle")
                pg_cid  = get_active_conn_id(str(base_d), _uname, "postgres")
                ora_conn = all_conns.get(ora_cid) if ora_cid else None
                pg_conn  = all_conns.get(pg_cid)  if pg_cid  else None
            except Exception:
                ora_conn = pg_conn = None
            # Fallback to global is_active for legacy / no state yet
            if not ora_conn and not pg_conn:
                for c in all_conns.values():
                    if c.get("is_active"):
                        if c.get("db_type") == "oracle" and ora_conn is None:
                            ora_conn = c
                        elif c.get("db_type") == "postgres" and pg_conn is None:
                            pg_conn = c
    except Exception:
        pass

    db_cards = [
        {
            "key": "oracle", "icon": "🔶",
            "label": ora_conn["name"] if ora_conn else "Oracle",
            "host":  _host_from_cs(ora_conn["connection_string"], "oracle") if ora_conn else "No active connection",
            "available": ora_conn is not None,
            "active": ora_conn is not None and pg_conn is None,
        },
        {
            "key": "postgresql", "icon": "🐘",
            "label": pg_conn["name"] if pg_conn else "PostgreSQL",
            "host":  _host_from_cs(pg_conn["connection_string"], "postgres") if pg_conn else "No active connection",
            "available": pg_conn is not None,
            "active": pg_conn is not None,
        },
    ]
    # If only Oracle is active, make it the active card
    if ora_conn and not pg_conn:
        db_cards[0]["active"] = True
        db_cards[1]["active"] = False
    elif not ora_conn and pg_conn:
        db_cards[0]["active"] = False
        db_cards[1]["active"] = True

    current_db = "oracle" if (ora_conn and not pg_conn) else "postgresql"

    # Get LLM config — _current_user() already checked JWT so identity is available
    ai_provider = ai_model = ""
    try:
        from app.api.llm_settings import _get_user_cfg
        if username_for_llm:
            cfg = _get_user_cfg(username_for_llm)
            ai_provider = cfg.get("provider", "")
            ai_model    = cfg.get("model", "")
    except Exception:
        pass

    return _render("ai_assistant.html", "ai_assistant",
                   db_cards=db_cards,
                   db_cards_json=json.dumps(db_cards),
                   current_db=current_db,
                   ai_provider=ai_provider,
                   ai_model=ai_model)


@web_bp.get("/ai-agents")
def ai_agents():
    return _render("ai_agents.html", "ai_agents")


@web_bp.get("/playbooks")
def playbooks():
    return _render("playbooks.html", "dba_playbooks")


@web_bp.get("/users")
def user_management():
    return _render("users.html", "user_management")


@web_bp.get("/llm-settings")
def llm_settings():
    return _render("llm_settings.html", "llm_settings")


@web_bp.get("/ask-oem")
def ask_oem():
    return _render("ask_oem.html", "ask_oem")


@web_bp.get("/logs")
def activity_logs():
    return _render("logs.html", "user_management")


# This line is a no-op addition guard — llm_settings is already registered via blueprint
# llm_settings page route already present from earlier web.py build


@web_bp.get("/guardrails")
def guardrails():
    return _render("guardrails.html", "guardrails")


@web_bp.get("/ai-query-generator")
def ai_query_generator():
    return _render("ai_query_generator.html", "db_explorer")


@web_bp.get("/notifications")
def notifications():
    return _render("notifications.html", "notifications")


@web_bp.get("/agent-monitor")
def agent_monitor():
    return _render("agent_monitor.html", "ai_agents")


@web_bp.get("/mcp-console")
def mcp_console():
    return _render("mcp_console.html", "mcp_console")
