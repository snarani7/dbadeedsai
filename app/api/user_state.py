"""
app/api/user_state.py — Per-user active database connection state.

Each user's active connection choice is stored independently in
data/user_state/<username>.json so activating a connection for one
user does not affect any other user.

Schema:
  { "oracle_active": "<conn_id>|null",
    "postgres_active": "<conn_id>|null",
    "updated_at": "<iso>" }
"""
from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path


def _path(base_dir: str, username: str) -> Path:
    p = Path(base_dir) / "data" / "user_state"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{username}.json"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_user_state(base_dir: str, username: str) -> dict:
    f = _path(base_dir, username)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"oracle_active": None, "postgres_active": None}


def get_active_conn_id(base_dir: str, username: str, db_type: str) -> str | None:
    return get_user_state(base_dir, username).get(f"{db_type}_active")


def set_active_conn(base_dir: str, username: str, db_type: str,
                    conn_id: str | None) -> None:
    state = get_user_state(base_dir, username)
    state[f"{db_type}_active"] = conn_id
    state["updated_at"] = _now()
    _path(base_dir, username).write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
