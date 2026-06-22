"""
app/api/guardrails.py  —  Admin management API for all 3 guardrails.

GET  /api/guardrails/status          → full status of all 3 guardrails
GET  /api/guardrails/pii-config      → full PII blacklist JSON config
POST /api/guardrails/pii-config      → save updated PII config + hot-reload
POST /api/guardrails/pii-reload      → reload blacklist from disk
GET  /api/guardrails/content-filter  → keyword list grouped by category
GET  /api/guardrails/safety-info     → SQL safety blocked operations list
GET  /api/guardrails/stats           → block event counts per guardrail
GET  /api/guardrails/logs            → recent block/redact events from all logs
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, UTC
from pathlib import Path
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt

sys.path.insert(0, str(Path(__file__).parents[3]))

guardrails_bp = Blueprint("guardrails", __name__)

_PII_CFG = os.getenv("PII_BLACKLIST_FILE", "data/pii_blacklist.json")
_PII_LOG = "logs/pii_access.log"
_SAFE_LOG = "logs/safety_blocks.log"


def _require_admin():
    if "user_management" not in get_jwt().get("permissions", []):
        return jsonify({"error": "Admin permission required"}), 403


# ── Status ────────────────────────────────────────────────────────────────────
@guardrails_bp.get("/status")
@jwt_required()
def status():
    if err := _require_admin(): return err
    from pii_blacklist_protection import get_pii_status
    from content_filter import ChatContentFilter
    from sql_safety import SQLSafetyValidator
    pii = get_pii_status()
    return jsonify({"guardrails": {
        "content_filter": {
            "enabled": True,
            "keyword_count": len(ChatContentFilter.RESTRICTED_KEYWORDS),
            "description": "Blocks inappropriate/off-topic questions in all AI features",
            "applied_to": ["AI Assistant", "AI Agents", "AskDBA", "SQL Generate"],
        },
        "sql_safety": {
            "enabled": True,
            "blocked_leading": SQLSafetyValidator.DANGEROUS_LEADING_KEYWORDS,
            "blocked_inline": SQLSafetyValidator.DANGEROUS_INLINE_KEYWORDS,
            "pattern_count": len(SQLSafetyValidator.DANGEROUS_FUNCTION_PATTERNS),
            "description": "Prevents DDL/DML and dangerous DB functions",
            "applied_to": ["DB Explorer Execute", "DB Explorer Explain",
                           "SQL Generate", "AskDBA Agent SQL", "AI Agent SQL"],
        },
        "pii_blacklist": {
            "enabled": pii["enabled"],
            "mode": pii["mode"],
            "blocked_tables_oracle": pii["blocked_oracle"],
            "blocked_tables_postgres": pii["blocked_postgres"],
            "pii_column_tables": len(pii["pii_map_oracle"]) + len(pii["pii_map_postgres"]),
            "column_patterns": len(pii["patterns"]),
            "exempt_users": pii["exempt_users"],
            "description": "Blocks/redacts PII tables and columns, logs all access",
            "applied_to": ["DB Explorer Execute", "SQL Generate",
                           "AI Assistant", "AI Agents", "AskDBA"],
        },
    }, "as_of": datetime.now(UTC).isoformat(timespec="seconds")}), 200


# ── PII Config ────────────────────────────────────────────────────────────────
@guardrails_bp.get("/pii-config")
@jwt_required()
def get_pii_config():
    if err := _require_admin(): return err
    try:
        cfg = json.loads(Path(_PII_CFG).read_text(encoding="utf-8"))
        return jsonify({"config": cfg}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@guardrails_bp.post("/pii-config")
@jwt_required()
def save_pii_config():
    if err := _require_admin(): return err
    cfg = (request.get_json(silent=True) or {}).get("config")
    if not cfg: return jsonify({"error": "config body required"}), 400
    try:
        Path(_PII_CFG).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        from pii_blacklist_protection import reload_blacklist
        reload_blacklist()
        return jsonify({"message": "PII config saved and reloaded"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@guardrails_bp.post("/pii-reload")
@jwt_required()
def reload_pii():
    if err := _require_admin(): return err
    from pii_blacklist_protection import reload_blacklist
    reload_blacklist()
    return jsonify({"message": "PII blacklist reloaded from disk",
                    "reloaded_at": datetime.now(UTC).isoformat(timespec="seconds")}), 200


# ── Content Filter info ───────────────────────────────────────────────────────
@guardrails_bp.get("/content-filter")
@jwt_required()
def content_filter_info():
    if err := _require_admin(): return err
    from content_filter import ChatContentFilter
    kws = ChatContentFilter.RESTRICTED_KEYWORDS
    cats = {
        "Adult / Inappropriate": ["adult","porn","sex","sexual","nude","naked","xxx","erotic"],
        "Violence / Abuse":      ["abuse","violence","violent","kill","murder","torture","harm","hurt"],
        "Political":             ["political","politics","election","vote","democrat","republican",
                                  "liberal","conservative","trump","biden","government conspiracy"],
        "Hate Speech":           ["racist","racism","sexist","sexism","hate speech","discrimination"],
        "Illegal Activities":    ["illegal","hack into","crack password","pirate","steal data"],
        "Dangerous SQL":         [k for k in kws if any(s in k for s in
                                  ["drop","delete","truncate","alter","update","insert","grant","revoke","remove"])],
    }
    return jsonify({"total": len(kws), "categories": cats, "all_keywords": kws}), 200


# ── SQL Safety info ───────────────────────────────────────────────────────────
@guardrails_bp.get("/safety-info")
@jwt_required()
def safety_info():
    if err := _require_admin(): return err
    from sql_safety import SQLSafetyValidator, get_safety_help
    return jsonify({
        "blocked_leading":     SQLSafetyValidator.DANGEROUS_LEADING_KEYWORDS,
        "blocked_inline":      SQLSafetyValidator.DANGEROUS_INLINE_KEYWORDS,
        "pattern_count":       len(SQLSafetyValidator.DANGEROUS_FUNCTION_PATTERNS),
        "help_text":           get_safety_help(),
    }), 200


# ── Stats ─────────────────────────────────────────────────────────────────────
@guardrails_bp.get("/stats")
@jwt_required()
def get_stats():
    if err := _require_admin(): return err
    today = datetime.now().strftime("%Y-%m-%d")
    stats = {k: {"total":0,"today":0} for k in
             ["content_filter","sql_safety","pii_blocked","pii_redacted"]}
    for path in [_PII_LOG, _SAFE_LOG]:
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                    et, src, ts = e.get("event_type",""), e.get("source",""), e.get("timestamp","")
                    is_today = ts.startswith(today)
                    def bump(k):
                        stats[k]["total"] += 1
                        if is_today: stats[k]["today"] += 1
                    if "redacted" in et:       bump("pii_redacted")
                    elif "pii" in et or "pii" in src or "blocked_table" in et: bump("pii_blocked")
                    elif "content_filter" in src: bump("content_filter")
                    elif "sql_safety" in src or "safety" in et: bump("sql_safety")
                except Exception: pass
        except FileNotFoundError: pass
    return jsonify({"stats": stats, "as_of": datetime.now(UTC).isoformat(timespec="seconds")}), 200


# ── Logs ──────────────────────────────────────────────────────────────────────
@guardrails_bp.get("/logs")
@jwt_required()
def get_logs():
    if err := _require_admin(): return err
    limit   = min(int(request.args.get("limit", 200)), 1000)
    gtype   = request.args.get("type", "")   # content_filter | sql_safety | pii
    entries = []
    for path in [_PII_LOG, _SAFE_LOG]:
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines()[-limit:]:
                try:
                    e = json.loads(line)
                    # tag each entry with guardrail type
                    et, src = e.get("event_type",""), e.get("source","")
                    if "redacted" in et or "pii" in et or "pii" in src or "blocked_table" in et:
                        e["_guardrail"] = "pii_blacklist"
                    elif "content_filter" in src:
                        e["_guardrail"] = "content_filter"
                    else:
                        e["_guardrail"] = "sql_safety"
                    entries.append(e)
                except Exception: pass
        except FileNotFoundError: pass
    entries.sort(key=lambda e: e.get("timestamp",""), reverse=True)
    if gtype:
        entries = [e for e in entries if e.get("_guardrail","") == gtype]
    return jsonify({"entries": entries[:limit], "total": len(entries), "limit": limit}), 200


# ── Live Guardrail Test ────────────────────────────────────────────────────────
@guardrails_bp.post("/test")
@jwt_required()
def test_guardrails():
    """
    Test a SQL query or NL prompt against all 3 guardrail layers.
    Returns per-layer pass/fail with detail messages.
    """
    data     = request.get_json(silent=True) or {}
    text     = (data.get("text") or "").strip()
    db_type  = (data.get("db_type") or "postgresql").lower()
    is_nl    = data.get("is_nl", False)   # True = natural language prompt, False = SQL

    if not text:
        return jsonify({"error": "text is required"}), 400

    username = "test_user"  # non-exempt test user

    result = {
        "text":    text[:300],
        "db_type": db_type,
        "layers":  []
    }

    # ── Layer 1: Content Filter ──────────────────────────────────────
    try:
        from content_filter import validate_chat_question
        cf_ok, cf_msg = validate_chat_question(text)
        result["layers"].append({
            "layer":    1,
            "name":     "Content Filter",
            "icon":     "🚫",
            "passed":   cf_ok,
            "status":   "PASS" if cf_ok else "BLOCKED",
            "message":  "No restricted content detected" if cf_ok else cf_msg.strip(),
        })
    except Exception as exc:
        result["layers"].append({"layer": 1, "name": "Content Filter",
                                  "icon": "🚫", "passed": True,
                                  "status": "SKIP", "message": str(exc)})

    # ── Layer 2: SQL Safety (skip for NL prompts) ────────────────────
    sql_to_test = None if is_nl else text
    if sql_to_test:
        try:
            from sql_safety import validate_sql, get_safety_help
            safe, smsg = validate_sql(sql_to_test, allow_select_only=True)
            result["layers"].append({
                "layer":   2,
                "name":    "SQL Safety",
                "icon":    "🔒",
                "passed":  safe,
                "status":  "PASS" if safe else "BLOCKED",
                "message": smsg,
            })
        except Exception as exc:
            result["layers"].append({"layer": 2, "name": "SQL Safety",
                                      "icon": "🔒", "passed": True,
                                      "status": "SKIP", "message": str(exc)})
    else:
        result["layers"].append({
            "layer":   2,
            "name":    "SQL Safety",
            "icon":    "🔒",
            "passed":  True,
            "status":  "SKIP",
            "message": "SQL Safety applies to SQL queries only",
        })

    # ── Layer 3: PII Blacklist ────────────────────────────────────────
    sql_for_pii = None if is_nl else text
    if sql_for_pii:
        try:
            from pii_blacklist_protection import validate_pii
            pii_ok, pii_msg, pii_det = validate_pii(sql_for_pii, username, db_type)
            blocked = not pii_ok
            warning = pii_det.get("pii_warning", False)
            agg     = pii_det.get("aggregated", False)
            clean   = pii_det.get("clean", False)

            if blocked:
                status = "BLOCKED"
            elif warning:
                status = "REDACT"
            elif agg:
                status = "AGG_SAFE"
            else:
                status = "PASS"

            result["layers"].append({
                "layer":        3,
                "name":         "PII Blacklist",
                "icon":         "🛡️",
                "passed":       not blocked,
                "status":       status,
                "message":      pii_msg,
                "pii_columns":  pii_det.get("pii_columns", []),
                "blocked_tables": pii_det.get("blocked_tables", []),
            })
        except Exception as exc:
            result["layers"].append({"layer": 3, "name": "PII Blacklist",
                                      "icon": "🛡️", "passed": True,
                                      "status": "SKIP", "message": str(exc)})
    else:
        result["layers"].append({
            "layer":   3,
            "name":    "PII Blacklist",
            "icon":    "🛡️",
            "passed":  True,
            "status":  "SKIP",
            "message": "PII Blacklist applies to SQL queries only",
        })

    # Overall verdict
    all_passed = all(l["passed"] for l in result["layers"])
    result["verdict"] = "ALLOWED" if all_passed else "BLOCKED"

    return jsonify(result), 200
