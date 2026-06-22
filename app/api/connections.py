"""
app/api/connections.py — Database connection management.

User-friendly: supports separate Oracle / PostgreSQL form fields
(name, host, port, user, password, service/dbname) so users never
have to hand-type connection strings.

Routes:
  GET    /api/connections/              → list all
  POST   /api/connections/             → create (form-fields OR raw conn_str)
  GET    /api/connections/<id>         → get one
  PUT    /api/connections/<id>         → update
  DELETE /api/connections/<id>         → delete
  POST   /api/connections/<id>/test    → live test
  PUT    /api/connections/<id>/activate→ set as active
  GET    /api/connections/active       → active connections per db_type
"""

from __future__ import annotations

import json
import uuid
import os
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from activity_logger import log_database_connection
from app.api.user_state import get_active_conn_id, set_active_conn, get_user_state

connections_bp = Blueprint("connections", __name__)


# ── File helpers ───────────────────────────────────────────────────────────────

def _conn_file() -> Path:
    return Path(current_app.config.get(
        "DB_CONNECTIONS_FILE",
        os.getenv("DB_CONNECTIONS_FILE", "data/db_connections.json"),
    ))


def _load() -> dict[str, dict]:
    f = _conn_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict[str, dict]) -> None:
    f = _conn_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Connection string builder ──────────────────────────────────────────────────

def _build_oracle_cs(host: str, port: str, service: str, user: str, password: str) -> str:
    return f"{user}/{password}@{host}:{port}/{service}"


def _build_postgres_cs(host: str, port: str, dbname: str, user: str, password: str) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _mask(conn_str: str, db_type: str) -> str:
    match db_type:
        case "oracle" if "/" in conn_str and "@" in conn_str:
            user_part, host = conn_str.split("@", 1)
            user = user_part.split("/")[0]
            return f"{user}/****@{host}"
        case "postgres" if "://" in conn_str and "@" in conn_str:
            proto, rest     = conn_str.split("://", 1)
            user_pass, host = rest.split("@", 1)
            user            = user_pass.split(":")[0]
            return f"{proto}://{user}:****@{host}"
        case _:
            return conn_str


def _parse_fields_from_cs(conn_str: str, db_type: str) -> dict:
    """Extract host/port/user/service_or_db from a raw connection string."""
    fields: dict = {"host": "", "port": "", "db_user": "", "service_or_db": ""}
    try:
        match db_type:
            case "oracle" if "@" in conn_str:
                up, rest = conn_str.split("@", 1)
                fields["db_user"] = up.split("/")[0]
                host_svc = rest.rsplit("/", 1)
                if len(host_svc) == 2:
                    host_port, fields["service_or_db"] = host_svc
                    if ":" in host_port:
                        fields["host"], fields["port"] = host_port.rsplit(":", 1)
                    else:
                        fields["host"] = host_port
            case "postgres" if "://" in conn_str and "@" in conn_str:
                rest = conn_str.split("://", 1)[1]
                up, hr = rest.split("@", 1)
                fields["db_user"] = up.split(":")[0]
                hr2, dbn = hr.rsplit("/", 1)
                fields["service_or_db"] = dbn
                if ":" in hr2:
                    fields["host"], fields["port"] = hr2.rsplit(":", 1)
                else:
                    fields["host"] = hr2
    except Exception:
        pass
    return fields


def _safe(cid: str, conn: dict) -> dict:
    """Public-safe representation (no raw password in conn_str)."""
    # Auto-populate friendly fields if not stored (legacy connections)
    host         = conn.get("host", "")
    port         = conn.get("port", "")
    db_user      = conn.get("db_user", "")
    service_or_db = conn.get("service_or_db", "")
    if not host and conn.get("connection_string"):
        parsed = _parse_fields_from_cs(conn["connection_string"], conn.get("db_type", ""))
        host          = parsed["host"]
        port          = parsed["port"]
        db_user       = parsed["db_user"]
        service_or_db = parsed["service_or_db"]
    return {
        "id":                cid,
        "name":              conn.get("name", ""),
        "db_type":           conn.get("db_type", ""),
        "connection_string": _mask(conn.get("connection_string", ""), conn.get("db_type", "")),
        "host":              host,
        "port":              port,
        "db_user":           db_user,
        "service_or_db":     service_or_db,
        "is_active":         conn.get("is_active", False),
        "status":            conn.get("status", "untested"),
        "imported_from":     conn.get("imported_from"),
    }


def _require_perm() -> tuple | None:
    if "db_connections" not in get_jwt().get("permissions", []):
        return jsonify({"error": "db_connections permission required"}), 403
    return None


def _caller() -> str:
    try:
        return get_jwt_identity()
    except Exception:
        return "unknown"


def _base_dir() -> str:
    try:
        from flask import current_app
        return str(current_app.config.get("BASE_DIR", "."))
    except Exception:
        return "."


def _is_admin(perms: list) -> bool:
    return "user_management" in perms


# ── List ───────────────────────────────────────────────────────────────────────

@connections_bp.get("/")
@jwt_required()
def list_connections():
    if err := _require_perm(): return err
    username = _caller()
    perms    = get_jwt().get("permissions", [])
    all_c    = _load()
    base     = _base_dir()
    state    = get_user_state(base, username)
    result   = []
    for cid, c in all_c.items():
        # Non-admins only see their own connections + shared (no owner field = legacy/admin)
        owner = c.get("owner", "admin")
        if not _is_admin(perms) and owner != username and owner != "admin":
            continue
        safe = _safe(cid, c)
        # is_active is now per-user
        safe["is_active"] = (state.get(f"{c.get('db_type')}_active") == cid)
        result.append(safe)
    return jsonify({"connections": result, "total": len(result)}), 200


# ── Create ─────────────────────────────────────────────────────────────────────

@connections_bp.post("/")
@jwt_required()
def create_connection():
    if err := _require_perm(): return err
    data = request.get_json(silent=True) or {}

    name    = (data.get("name") or "").strip()
    db_type = (data.get("db_type") or "").lower()
    errors: list[str] = []

    if not name:    errors.append("name is required")
    if db_type not in ("oracle", "postgres"):
        errors.append("db_type must be 'oracle' or 'postgres'")

    # Accept either a raw connection_string OR individual fields
    conn_str  = (data.get("connection_string") or "").strip()
    host      = (data.get("host")         or "").strip()
    port      = (data.get("port")         or "").strip()
    db_user   = (data.get("db_user")      or "").strip()
    password  = (data.get("password")     or "").strip()
    service   = (data.get("service_or_db") or data.get("service") or data.get("dbname") or "").strip()

    if not conn_str:
        # Build from fields
        if not host:     errors.append("host is required (or provide connection_string)")
        if not port:     errors.append("port is required (or provide connection_string)")
        if not db_user:  errors.append("db_user is required")
        if not password: errors.append("password is required")
        if not service:  errors.append("service/dbname is required")
        if not errors:
            match db_type:
                case "oracle":
                    conn_str = _build_oracle_cs(host, port, service, db_user, password)
                case "postgres":
                    conn_str = _build_postgres_cs(host, port, service, db_user, password)
    else:
        # Extract fields from raw conn_str for storage
        try:
            match db_type:
                case "oracle" if "@" in conn_str:
                    up, rest = conn_str.split("@", 1)
                    db_user  = up.split("/")[0]
                    host, svc = rest.rsplit("/", 1)
                    if ":" in host: host, port = host.rsplit(":", 1)
                    service  = svc
                case "postgres" if "://" in conn_str:
                    rest     = conn_str.split("://", 1)[1]
                    up, hr   = rest.split("@", 1)
                    db_user  = up.split(":")[0]
                    hr2, dbn = hr.rsplit("/", 1)
                    if ":" in hr2: host, port = hr2.rsplit(":", 1)
                    else: host = hr2
                    service = dbn
        except Exception:
            pass

    if errors:
        return jsonify({"errors": errors}), 400

    conns  = _load()
    new_id = f"{db_type}_{uuid.uuid4().hex[:8]}"
    conns[new_id] = {
        "name": name, "db_type": db_type,
        "connection_string": conn_str,
        "host": host, "port": port,
        "db_user": db_user, "service_or_db": service,
        "is_active": False, "status": "untested",
        "owner": _caller(),
    }
    _save(conns)
    log_database_connection(_caller(), name, db_type, "create")
    return jsonify(_safe(new_id, conns[new_id])), 201


# ── Get one ────────────────────────────────────────────────────────────────────

@connections_bp.get("/<conn_id>")
@jwt_required()
def get_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404
    return jsonify(_safe(conn_id, conns[conn_id])), 200


# ── Update ─────────────────────────────────────────────────────────────────────

@connections_bp.put("/<conn_id>")
@jwt_required()
def update_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404

    conn = conns[conn_id]
    data = request.get_json(silent=True) or {}

    if name := data.get("name", "").strip():
        conn["name"] = name

    # Allow updating individual fields
    for field in ("host", "port", "db_user", "service_or_db"):
        if field in data:
            conn[field] = data[field].strip()

    # If password provided, rebuild connection string
    password = data.get("password", "").strip()
    needs_rebuild = password or any(f in data for f in ("host", "port", "db_user", "service_or_db"))

    if needs_rebuild and not data.get("connection_string"):
        h  = conn.get("host", "")
        p  = conn.get("port", "")
        u  = conn.get("db_user", "")
        sv = conn.get("service_or_db", "")
        if h and p and u and sv and password:
            match conn["db_type"]:
                case "oracle":
                    conn["connection_string"] = _build_oracle_cs(h, p, sv, u, password)
                case "postgres":
                    conn["connection_string"] = _build_postgres_cs(h, p, sv, u, password)
            conn["status"] = "untested"
    elif cs := data.get("connection_string", "").strip():
        conn["connection_string"] = cs
        conn["status"] = "untested"

    _save(conns)
    log_database_connection(_caller(), conn.get("name",""), conn["db_type"], "update")
    return jsonify(_safe(conn_id, conn)), 200


# ── Delete ─────────────────────────────────────────────────────────────────────

@connections_bp.delete("/<conn_id>")
@jwt_required()
def delete_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404
    name    = conns[conn_id].get("name", "")
    db_type = conns[conn_id].get("db_type", "")
    del conns[conn_id]
    _save(conns)
    log_database_connection(_caller(), name, db_type, "delete")
    return jsonify({"message": f"Connection '{conn_id}' deleted"}), 200


# ── Test ───────────────────────────────────────────────────────────────────────

@connections_bp.post("/<conn_id>/test")
@jwt_required()
def test_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404

    conn    = conns[conn_id]
    db_type = conn["db_type"]
    cs      = conn["connection_string"]
    name    = conn.get("name", "")

    try:
        match db_type:
            case "oracle":
                import oracledb
                user, rest = cs.split("@", 1)
                u, pw      = user.split("/", 1)
                c = oracledb.connect(user=u, password=pw, dsn=rest, timeout=5)
                c.cursor().execute("SELECT 'ok' FROM dual")
                c.close()
            case "postgres":
                import psycopg2
                c = psycopg2.connect(cs, connect_timeout=5)
                c.cursor().execute("SELECT 1")
                c.close()
            case _:
                return jsonify({"error": f"Unsupported db_type: {db_type!r}"}), 400

        conn["status"] = "connected"
        _save(conns)
        log_database_connection(_caller(), name, db_type, "test", success=True)
        return jsonify({"status": "connected", "message": "✓ Connection successful"}), 200

    except Exception as exc:
        conn["status"] = "failed"
        _save(conns)
        log_database_connection(_caller(), name, db_type, "test",
                                success=False, error=str(exc))
        return jsonify({"status": "failed", "message": f"✗ {exc}"}), 200


# ── Activate ───────────────────────────────────────────────────────────────────

@connections_bp.put("/<conn_id>/activate")
@jwt_required()
def activate_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404

    conn    = conns[conn_id]
    db_type = conn.get("db_type", "")
    username = _caller()
    set_active_conn(_base_dir(), username, db_type, conn_id)
    log_database_connection(username, conn.get("name",""), db_type, "activate")
    return jsonify({"message": f"Connection '{conn_id}' is now active for {username}"}), 200


@connections_bp.put("/<conn_id>/deactivate")
@jwt_required()
def deactivate_connection(conn_id: str):
    if err := _require_perm(): return err
    conns = _load()
    if conn_id not in conns:
        return jsonify({"error": "Connection not found"}), 404
    db_type  = conns[conn_id].get("db_type", "")
    username = _caller()
    set_active_conn(_base_dir(), username, db_type, None)
    return jsonify({"message": "Deactivated"}), 200


@connections_bp.get("/active")
@jwt_required()
def get_active():
    if err := _require_perm(): return err
    username = _caller()
    base     = _base_dir()
    all_c    = _load()
    active   = {}
    for db_type in ("oracle", "postgres"):
        cid = get_active_conn_id(base, username, db_type)
        if cid and cid in all_c:
            s = _safe(cid, all_c[cid])
            s["is_active"] = True
            active[db_type] = s
        else:
            # Fallback: global is_active (legacy connections without user_state)
            for cid2, c in all_c.items():
                if c.get("db_type") == db_type and c.get("is_active"):
                    active[db_type] = _safe(cid2, c)
                    break
    return jsonify({"active": active}), 200
