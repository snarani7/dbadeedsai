"""
app/api/users.py — User management endpoints (admin only).

Python 3.14 features used:
  • match/case            — validation error dispatch
  • walrus :=             — inline user lookups
  • datetime.now(UTC)     — ISO timestamps
  • list comprehension typing  — list[str]
  • X | None              — return hints

Routes:
  GET    /api/users/                   → list all
  POST   /api/users/                   → create
  GET    /api/users/<username>         → get one
  PUT    /api/users/<username>         → update
  DELETE /api/users/<username>         → delete
  PUT    /api/users/<username>/activate
  PUT    /api/users/<username>/deactivate
  GET    /api/users/permissions/available
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

sys.path.insert(0, str(Path(__file__).parents[3]))
from user_management import (
    load_users, save_users, hash_password,
    ALL_PERMISSIONS, get_user_permissions,
)

users_bp = Blueprint("users", __name__)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,32}$")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _require_admin() -> tuple | None:
    if "user_management" not in get_jwt().get("permissions", []):
        return jsonify({"error": "Admin permission required"}), 403
    return None


def _safe_user(username: str, meta: dict) -> dict[str, object]:
    """Strip password hash from user data before returning."""
    return {
        "username":    username,
        "name":        meta.get("name", ""),
        "email":       meta.get("email", ""),
        "permissions": meta.get("permissions", []),
        "is_active":   meta.get("is_active", True),
        "created_at":  meta.get("created_at"),
        "last_login":  meta.get("last_login"),
    }


# ── List ───────────────────────────────────────────────────────────────────────

@users_bp.get("/")
@jwt_required()
def list_users():
    if err := _require_admin():
        return err
    users  = load_users()
    result = [_safe_user(u, m) for u, m in users.items()]
    return jsonify({"users": result, "total": len(result)}), 200


# ── Create ─────────────────────────────────────────────────────────────────────

@users_bp.post("/")
@jwt_required()
def create_user():
    if err := _require_admin():
        return err

    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    name     = (data.get("name")     or "").strip()
    password = data.get("password", "")
    email    = (data.get("email")    or "").strip()
    perms    = data.get("permissions") or []
    active   = bool(data.get("is_active", True))

    # Collect all validation errors before returning
    errors: list[str] = []
    match (bool(username), _USERNAME_RE.fullmatch(username) if username else None):
        case (False, _):
            errors.append("username is required")
        case (True, None):
            errors.append("username: 3–32 chars, letters/digits/_ - only")

    if not name:
        errors.append("name is required")
    if not password or len(password) < 8:
        errors.append("password must be at least 8 characters")
    if not perms:
        errors.append("at least one permission is required")
    if bad := [p for p in perms if p not in ALL_PERMISSIONS]:
        errors.append(f"unknown permissions: {bad}")

    if errors:
        return jsonify({"errors": errors}), 400

    users = load_users()
    if username in users:
        return jsonify({"error": f"User '{username}' already exists"}), 409

    users[username] = {
        "name":          name,
        "password_hash": hash_password(password),
        "permissions":   perms,
        "email":         email,
        "is_active":     active,
        "created_at":    _iso_now(),
        "last_login":    None,
    }
    save_users(users)
    return jsonify(_safe_user(username, users[username])), 201


# ── Get one ────────────────────────────────────────────────────────────────────

@users_bp.get("/<username>")
@jwt_required()
def get_user(username: str):
    if err := _require_admin():
        return err
    users = load_users()
    if not (user := users.get(username)):
        return jsonify({"error": "User not found"}), 404
    return jsonify(_safe_user(username, user)), 200


# ── Update ─────────────────────────────────────────────────────────────────────

@users_bp.put("/<username>")
@jwt_required()
def update_user(username: str):
    if err := _require_admin():
        return err

    users  = load_users()
    if not (user := users.get(username)):
        return jsonify({"error": "User not found"}), 404

    caller = get_jwt_identity()
    data   = request.get_json(silent=True) or {}

    if (name := data.get("name", "").strip()):
        user["name"] = name

    if "email" in data:
        user["email"] = data["email"].strip()

    if "permissions" in data:
        new_perms = data["permissions"]
        match (caller == username, "user_management" not in new_perms):
            case (True, True):
                return jsonify({"error": "Cannot remove your own user_management permission"}), 400
        if bad := [p for p in new_perms if p not in ALL_PERMISSIONS]:
            return jsonify({"error": f"Unknown permissions: {bad}"}), 400
        if not new_perms:
            return jsonify({"error": "At least one permission required"}), 400
        user["permissions"] = new_perms

    if "is_active" in data:
        if caller == username and not data["is_active"]:
            return jsonify({"error": "Cannot deactivate your own account"}), 400
        user["is_active"] = bool(data["is_active"])

    if pwd := data.get("password", ""):
        if len(pwd) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        user["password_hash"] = hash_password(pwd)

    save_users(users)
    return jsonify(_safe_user(username, user)), 200


# ── Delete ─────────────────────────────────────────────────────────────────────

@users_bp.delete("/<username>")
@jwt_required()
def delete_user(username: str):
    if err := _require_admin():
        return err
    if (caller := get_jwt_identity()) == username:
        return jsonify({"error": "Cannot delete your own account"}), 400
    users = load_users()
    if username not in users:
        return jsonify({"error": "User not found"}), 404
    del users[username]
    save_users(users)
    return jsonify({"message": f"User '{username}' deleted",
                    "deleted_at": _iso_now()}), 200


# ── Activate / Deactivate ──────────────────────────────────────────────────────

@users_bp.put("/<username>/activate")
@jwt_required()
def activate_user(username: str):
    if err := _require_admin():
        return err
    users = load_users()
    if username not in users:
        return jsonify({"error": "User not found"}), 404
    users[username]["is_active"] = True
    save_users(users)
    return jsonify({"message": f"User '{username}' activated"}), 200


@users_bp.put("/<username>/deactivate")
@jwt_required()
def deactivate_user(username: str):
    if err := _require_admin():
        return err
    if get_jwt_identity() == username:
        return jsonify({"error": "Cannot deactivate your own account"}), 400
    users = load_users()
    if username not in users:
        return jsonify({"error": "User not found"}), 404
    users[username]["is_active"] = False
    save_users(users)
    return jsonify({"message": f"User '{username}' deactivated"}), 200


# ── Available permissions ──────────────────────────────────────────────────────

@users_bp.get("/permissions/available")
@jwt_required()
def list_permissions():
    return jsonify({"permissions": ALL_PERMISSIONS}), 200
