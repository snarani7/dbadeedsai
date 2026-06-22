"""
app/api/auth.py — Authentication endpoints.

Python 3.14 features used:
  • X | None              — return type annotations
  • match/case            — password-change validation
  • walrus :=             — inline lookups
  • datetime.now(UTC)     — replaces deprecated utcnow()
  • pathlib               — sys.path resolution
  • set[str]              — token blocklist type hint

Routes:
  POST /api/auth/login
  POST /api/auth/refresh
  POST /api/auth/logout
  GET  /api/auth/me
  POST /api/auth/change-password
"""

from __future__ import annotations

import sys
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
    set_access_cookies, set_refresh_cookies, unset_jwt_cookies,
)

# ── Legacy module path (repo root contains user_management.py) ────────────────
sys.path.insert(0, str(Path(__file__).parents[3]))
from activity_logger import log_login, log_logout
from user_management import (
    load_users, save_users, verify_password,
    hash_password, get_user_permissions, record_last_login,
)

auth_bp = Blueprint("auth", __name__)

# In-memory revocation list — swap for Redis in production
_revoked: set[str] = set()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ── Login ──────────────────────────────────────────────────────────────────────

@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    users = load_users()

    # walrus: look up and check existence in one step
    if not (user := users.get(username)):
        log_login(username, success=False, reason="user_not_found")
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.get("is_active", True):
        log_login(username, success=False, reason="account_inactive")
        return jsonify({"error": "Account is inactive. Contact your administrator."}), 403

    if not verify_password(password, user["password_hash"]):
        log_login(username, success=False, reason="wrong_password")
        return jsonify({"error": "Invalid credentials"}), 401

    permissions   = get_user_permissions(username)
    claims        = {"name": user["name"], "permissions": permissions}
    access_token  = create_access_token(identity=username, additional_claims=claims)
    refresh_token = create_refresh_token(identity=username)

    record_last_login(username)
    log_login(username, success=True)

    expires_in = int(
        current_app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds()
    )

    response = jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "expires_in":    expires_in,
        "user": {
            "username":    username,
            "name":        user["name"],
            "email":       user.get("email", ""),
            "permissions": permissions,
        },
    })
    set_access_cookies(response, access_token)
    set_refresh_cookies(response, refresh_token)
    return response, 200


# ── Refresh ────────────────────────────────────────────────────────────────────

@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    users    = load_users()

    if not (user := users.get(identity, {})).get("is_active", True):
        return jsonify({"error": "Account inactive"}), 403

    permissions  = get_user_permissions(identity)
    claims       = {"name": user.get("name", identity), "permissions": permissions}
    access_token = create_access_token(identity=identity, additional_claims=claims)

    response = jsonify({"access_token": access_token})
    set_access_cookies(response, access_token)
    return response, 200


# ── Logout ─────────────────────────────────────────────────────────────────────

@auth_bp.post("/logout")
@jwt_required(verify_type=False)
def logout():
    identity = get_jwt_identity()
    if jti := get_jwt().get("jti"):
        _revoked.add(jti)
    log_logout(identity)
    response = jsonify({"message": "Logged out successfully"})
    unset_jwt_cookies(response)
    return response, 200


# ── Me ─────────────────────────────────────────────────────────────────────────

@auth_bp.get("/me")
@jwt_required()
def me():
    identity = get_jwt_identity()
    claims   = get_jwt()
    user     = load_users().get(identity, {})

    return jsonify({
        "username":    identity,
        "name":        claims.get("name", identity),
        "email":       user.get("email", ""),
        "permissions": claims.get("permissions", []),
        "last_login":  user.get("last_login"),
        "created_at":  user.get("created_at"),
    }), 200


# ── Change password ────────────────────────────────────────────────────────────

@auth_bp.post("/change-password")
@jwt_required()
def change_password():
    identity = get_jwt_identity()
    data     = request.get_json(silent=True) or {}
    current  = data.get("current_password", "")
    new_pwd  = data.get("new_password", "")

    match (bool(current), bool(new_pwd), len(new_pwd) >= 8):
        case (False, _, _):
            return jsonify({"error": "current_password is required"}), 400
        case (_, False, _):
            return jsonify({"error": "new_password is required"}), 400
        case (_, _, False):
            return jsonify({"error": "new_password must be at least 8 characters"}), 400

    users = load_users()
    if not (user := users.get(identity)):
        return jsonify({"error": "User not found"}), 404

    if not verify_password(current, user["password_hash"]):
        return jsonify({"error": "Current password is incorrect"}), 401

    users[identity]["password_hash"] = hash_password(new_pwd)
    save_users(users)
    return jsonify({"message": "Password changed successfully",
                    "changed_at": _iso_now()}), 200
