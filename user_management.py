#!/usr/bin/env python3
"""
user_management.py — Pure-Python user store for dbadeeds.ai Flask app.

No Streamlit dependencies. All I/O uses pathlib + json.
Compatible with Python 3.10+.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, UTC
from pathlib import Path

import bcrypt

# ── Config ─────────────────────────────────────────────────────────────────────
USERS_FILE = Path(os.getenv("USERS_FILE", "data/users.json"))

# ── Permission definitions (mirrors Streamlit gold copy) ──────────────────────
ALL_PERMISSIONS: dict[str, dict] = {
    "dashboard":       {"label": "Dashboard",           "icon": "📊", "group": "General"},
    "ai_assistant":    {"label": "AI Assistant",         "icon": "🤖", "group": "AI"},
    "ai_agents":       {"label": "AI Agents",            "icon": "🧠", "group": "AI"},
    "ai_query_generator": {"label": "AI Query Generator", "icon": "⚡", "group": "AI"},
    "llm_settings":    {"label": "LLM Settings",         "icon": "⚙️",  "group": "AI"},
    "ask_oem":         {"label": "Ask OEM",              "icon": "🔮", "group": "AI"},
    "db_connections":  {"label": "Database Connections", "icon": "🔌", "group": "Database"},
    "db_explorer":     {"label": "Database Explorer",    "icon": "🔍", "group": "Database"},
    "dba_playbooks":   {"label": "DBA Playbooks",        "icon": "📋", "group": "Database"},
    "user_management": {"label": "User Management",      "icon": "👥", "group": "Admin"},
    "guardrails":      {"label": "AI Guardrails",        "icon": "🛡️", "group": "Admin"},
    "notifications":   {"label": "Notifications",         "icon": "🔔", "group": "Admin"},
    "mcp_console":     {"label": "MCP Console",           "icon": "🔧", "group": "Admin"},
}

PERMISSION_GROUPS: list[str] = ["General", "AI", "Database", "Admin"]

PRESETS: dict[str, list[str]] = {
    "Admin (Full Access)": list(ALL_PERMISSIONS.keys()),
    "DBA":        ["dashboard", "ai_assistant", "ai_agents", "ai_query_generator", "db_connections", "db_explorer", "dba_playbooks"],
    "Analyst":    ["dashboard", "ai_assistant", "db_explorer"],
    "Support Desk": ["dashboard"],
    "Viewer":     ["dashboard"],
}

ROLE_TO_PERMISSIONS: dict[str, list[str]] = {
    "admin":   list(ALL_PERMISSIONS.keys()),
    "dbadmin": ["dashboard", "ai_assistant", "ai_agents", "db_connections", "db_explorer", "dba_playbooks"],
    "viewer":  ["dashboard"],
    "user":    ["dashboard"],
}

# Default seed users (first-run only)
_SEED_USERS: dict[str, dict] = {
    "admin": {
        "name": "Administrator",
        "plain_password": "2AHmoCcUN0KaJ7NrDkvX",
        "permissions": list(ALL_PERMISSIONS.keys()),
        "email": "admin@dbadeeds.ai",
    },
    "dbadmin": {
        "name": "Database Administrator",
        "plain_password": "DBAdmin@2024!Secure",
        "permissions": ROLE_TO_PERMISSIONS["dbadmin"],
        "email": "dbadmin@dbadeeds.ai",
    },
}


# ── Password helpers ───────────────────────────────────────────────────────────

def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False


def password_strength(pwd: str) -> tuple[int, str]:
    if len(pwd) < 6:
        return 0, "Too short"
    score = 0
    missing: list[str] = []
    for pattern, label in [
        (r"[A-Z]", "uppercase"), (r"[a-z]", "lowercase"),
        (r"\d", "number"),       (r"[^A-Za-z\d]", "symbol"),
    ]:
        if re.search(pattern, pwd):
            score += 1
        else:
            missing.append(label)
    if len(pwd) >= 12:
        score = min(4, score + 1)
    msg = {0: "Weak", 1: "Weak", 2: "Fair", 3: "Good", 4: "Strong"}.get(score, "Strong")
    if missing:
        msg += " — needs " + ", ".join(missing[:2])
    return score, msg


# ── Migration ──────────────────────────────────────────────────────────────────

def _migrate_user(meta: dict) -> dict:
    """Add missing fields / auto-grant new permissions to admin users."""
    if "permissions" not in meta:
        role = meta.get("role", "viewer")
        meta["permissions"] = ROLE_TO_PERMISSIONS.get(role, ["dashboard"])
        return meta

    # Auto-grant new permissions to admin users
    if "user_management" in meta.get("permissions", []):
        full    = list(ALL_PERMISSIONS.keys())
        current = set(meta["permissions"])
        meta["permissions"] = meta["permissions"] + [p for p in full if p not in current]

    # Ensure required fields exist
    meta.setdefault("is_active", True)
    meta.setdefault("email", "")
    meta.setdefault("last_login", None)
    return meta


# ── Persistence ────────────────────────────────────────────────────────────────

def _users_path() -> Path:
    p = Path(os.getenv("USERS_FILE", str(USERS_FILE)))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_users() -> dict[str, dict]:
    p = _users_path()
    if p.exists():
        try:
            users: dict[str, dict] = json.loads(p.read_text(encoding="utf-8"))
            changed = False
            for uname in users:
                before = json.dumps(users[uname], sort_keys=True)
                users[uname] = _migrate_user(users[uname])
                if json.dumps(users[uname], sort_keys=True) != before:
                    changed = True
            if changed:
                save_users(users)
            return users
        except Exception as exc:
            print(f"[user_management] load error: {exc}")
            return {}

    # First run — seed default users
    users = {}
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    for uname, meta in _SEED_USERS.items():
        users[uname] = {
            "name":          meta["name"],
            "password_hash": hash_password(meta["plain_password"]),
            "permissions":   meta["permissions"],
            "email":         meta["email"],
            "created_at":    now,
            "last_login":    None,
            "is_active":     True,
        }
    save_users(users)
    return users


def save_users(users: dict[str, dict]) -> bool:
    try:
        _users_path().write_text(json.dumps(users, indent=2, default=str), encoding="utf-8")
        return True
    except Exception as exc:
        print(f"[user_management] save error: {exc}")
        return False


def get_user_permissions(username: str) -> list[str]:
    try:
        users = load_users()
        if user := users.get(username):
            perms = user.get("permissions", [])
            if not perms and "role" in user:
                return ROLE_TO_PERMISSIONS.get(user["role"], ["dashboard"])
            return perms
    except Exception:
        pass
    return list(ALL_PERMISSIONS.keys()) if username == "admin" else ["dashboard"]


def has_permission(username: str, permission_key: str) -> bool:
    return permission_key in get_user_permissions(username)


def record_last_login(username: str) -> None:
    users = load_users()
    if username in users:
        users[username]["last_login"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        save_users(users)
