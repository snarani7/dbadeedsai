"""
app/api/conversations.py — Save / Open / Save As for all AI modules.

Stores conversations as JSON files:
  data/conversations/<username>/<module>/<id>.json

Routes:
  GET    /api/conversations/list          → list saved (filter by module)
  POST   /api/conversations/save         → create or overwrite
  GET    /api/conversations/<id>         → load one
  PUT    /api/conversations/<id>/rename  → rename
  DELETE /api/conversations/<id>         → delete
"""
from __future__ import annotations

import json, re, time
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from activity_logger import log_activity

conversations_bp = Blueprint("conversations", __name__)

VALID_MODULES = {"ai_assistant", "sql_editor", "ai_agents"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _base() -> Path:
    return Path(current_app.config.get("BASE_DIR", "."))

def _user_dir(username: str) -> Path:
    return _base() / "data" / "conversations" / username

def _conv_dir(username: str, module: str) -> Path:
    p = _user_dir(username) / module
    p.mkdir(parents=True, exist_ok=True)
    return p

def _index_file(username: str) -> Path:
    return _user_dir(username) / "index.json"

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe_id(s: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", s.lower())[:40]

def _auto_title(module: str, data: dict) -> str:
    for m in (data.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "user":
            t = (m.get("content") or "")[:60].strip()
            if t:
                return t + ("…" if len(m.get("content","")) > 60 else "")
    sql = (data.get("sql") or "")[:60].strip()
    if sql:
        return sql + ("…" if len(data.get("sql","")) > 60 else "")
    return f"Untitled {module.replace('_',' ').title()}"

def _load_index(username: str) -> list:
    f = _index_file(username)
    if f.exists():
        try: return json.loads(f.read_text(encoding="utf-8"))
        except Exception: pass
    return []

def _save_index(username: str, index: list) -> None:
    f = _index_file(username)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(index, indent=2), encoding="utf-8")

def _upsert_index(username: str, conv: dict) -> None:
    idx = _load_index(username)
    entry = {k: conv[k] for k in
             ("id","title","module","db_type","project","msg_count","created_at","updated_at")
             if k in conv}
    for i, x in enumerate(idx):
        if x["id"] == conv["id"]:
            idx[i] = entry; break
    else:
        idx.insert(0, entry)
    idx.sort(key=lambda x: x["updated_at"], reverse=True)
    _save_index(username, idx[:500])

def _remove_index(username: str, conv_id: str) -> None:
    _save_index(username, [x for x in _load_index(username) if x["id"] != conv_id])

def _require_perm():
    perms = get_jwt().get("permissions", [])
    if not any(p in perms for p in ("ai_assistant","db_explorer","admin","user_management")):
        return jsonify({"error": "Permission denied"}), 403


# ── routes ────────────────────────────────────────────────────────────────────

@conversations_bp.get("/list")
@jwt_required()
def list_conversations():
    if err := _require_perm(): return err
    username = get_jwt_identity()
    module   = request.args.get("module", "")
    search   = request.args.get("q", "").lower()
    limit    = min(int(request.args.get("limit", 100)), 200)
    idx = _load_index(username)
    if module and module in VALID_MODULES:
        idx = [x for x in idx if x.get("module") == module]
    if search:
        idx = [x for x in idx
               if search in x.get("title","").lower()
               or search in x.get("project","").lower()]
    return jsonify({"conversations": idx[:limit], "total": len(idx)}), 200


@conversations_bp.post("/save")
@jwt_required()
def save_conversation():
    if err := _require_perm(): return err
    username = get_jwt_identity()
    body     = request.get_json(silent=True) or {}
    module   = (body.get("module") or "").strip()
    if module not in VALID_MODULES:
        return jsonify({"error": f"module must be one of: {', '.join(VALID_MODULES)}"}), 400

    data      = body.get("data") or {}
    db_type   = (body.get("db_type") or "").strip()
    project   = (body.get("project") or "").strip()
    conv_id   = (body.get("id") or "").strip()
    title     = (body.get("title") or "").strip() or _auto_title(module, data)
    now       = _now()
    messages  = data.get("messages") or data.get("history") or []
    msg_count = len([m for m in messages if isinstance(m, dict) and m.get("role") == "user"])

    if conv_id:
        existing_file = _conv_dir(username, module) / f"{conv_id}.json"
        created_at = now
        if existing_file.exists():
            try: created_at = json.loads(existing_file.read_text())["created_at"]
            except Exception: pass
    else:
        conv_id    = f"{module[:3]}_{_safe_id(username)}_{int(time.time()*1000)}"
        created_at = now

    conv = {"id": conv_id, "title": title, "module": module,
            "db_type": db_type, "project": project, "msg_count": msg_count,
            "created_at": created_at, "updated_at": now, "data": data}

    (_conv_dir(username, module) / f"{conv_id}.json").write_text(
        json.dumps(conv, indent=2), encoding="utf-8")
    _upsert_index(username, conv)
    log_activity(username, "conversation_saved", f"{module} {conv_id} {title[:40]}")
    return jsonify({"ok": True, "id": conv_id, "title": title,
                    "msg_count": msg_count, "updated_at": now}), 200


@conversations_bp.get("/<conv_id>")
@jwt_required()
def load_conversation(conv_id: str):
    if err := _require_perm(): return err
    username = get_jwt_identity()
    for module in VALID_MODULES:
        f = _user_dir(username) / module / f"{conv_id}.json"
        if f.exists():
            try: return jsonify(json.loads(f.read_text(encoding="utf-8"))), 200
            except Exception as e: return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Conversation not found"}), 404


@conversations_bp.put("/<conv_id>/rename")
@jwt_required()
def rename_conversation(conv_id: str):
    if err := _require_perm(): return err
    username = get_jwt_identity()
    title    = (request.get_json(silent=True) or {}).get("title","").strip()
    if not title: return jsonify({"error": "title required"}), 400
    for module in VALID_MODULES:
        f = _user_dir(username) / module / f"{conv_id}.json"
        if f.exists():
            conv = json.loads(f.read_text(encoding="utf-8"))
            conv["title"] = title; conv["updated_at"] = _now()
            f.write_text(json.dumps(conv, indent=2), encoding="utf-8")
            _upsert_index(username, conv)
            return jsonify({"ok": True, "title": title}), 200
    return jsonify({"error": "Not found"}), 404


@conversations_bp.delete("/<conv_id>")
@jwt_required()
def delete_conversation(conv_id: str):
    if err := _require_perm(): return err
    username = get_jwt_identity()
    for module in VALID_MODULES:
        f = _user_dir(username) / module / f"{conv_id}.json"
        if f.exists():
            f.unlink(); _remove_index(username, conv_id)
            return jsonify({"ok": True}), 200
    return jsonify({"error": "Not found"}), 404


@conversations_bp.get("/export/<conv_id>")
@jwt_required()
def export_conversation(conv_id: str):
    if err := _require_perm(): return err
    username = get_jwt_identity()
    for module in VALID_MODULES:
        f = _user_dir(username) / module / f"{conv_id}.json"
        if f.exists():
            conv  = json.loads(f.read_text(encoding="utf-8"))
            fname = f"dbadeeds_{conv['module']}_{_safe_id(conv['title'])}.json"
            return send_file(f, mimetype="application/json",
                             as_attachment=True, download_name=fname)
    return jsonify({"error": "Not found"}), 404
