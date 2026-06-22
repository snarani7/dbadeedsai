"""
app/api/ai.py — AI Assistant chat (streaming SSE).

Architecture matches Streamlit exactly:
  - initialize_agent(ZERO_SHOT_REACT_DESCRIPTION) with real OracleQuery / PostgresQuery tools
  - Agent decides what SQL to run, executes via tool, interprets REAL results
  - Streams REACT step events (tool calls + observations) then final answer tokens

FIX: agent.run() executes in a background thread.  Flask's current_app proxy is
     request-local; we push an app context into the thread explicitly.

Routes:
  POST /api/ai/chat/stream     → SSE streaming agent chat
  GET  /api/ai/chat/history    → per-user chat history
  POST /api/ai/chat/clear      → clear history
  GET  /api/ai/providers       → current provider/model for logged-in user
"""
from __future__ import annotations

import json
import sys
import threading
import queue as qmodule
import time
from collections.abc import Generator
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, request, Response, jsonify, stream_with_context, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

ai_bp = Blueprint("ai", __name__)
sys.path.insert(0, str(Path(__file__).parents[2]))  # → final_flask/

# ── per-user chat history (in-memory, 20 exchanges) ──────────────────────────
_history: dict[str, list] = {}


def _require_ai():
    if "ai_assistant" not in get_jwt().get("permissions", []):
        return jsonify({"error": "ai_assistant permission required"}), 403


def _get_llm(username, override_provider=None, override_model=None, streaming=False):
    """Build LLM from saved config.  Safe to call inside or outside app context."""
    from app.api.llm_settings import build_llm, _get_user_cfg
    cfg = dict(_get_user_cfg(username))
    if override_provider:
        cfg["provider"] = override_provider
    if override_model:
        cfg["model"] = override_model
    return build_llm(cfg, streaming=streaming)


def _append_history(username: str, role: str, content: str):
    h = _history.setdefault(username, [])
    h.append({"role": role, "content": content,
               "ts": datetime.now(UTC).isoformat(timespec="seconds")})
    _history[username] = h[-40:]


def _ai_system_prompt(db_type: str) -> str:
    """System prompt — matches Streamlit context_prompt approach."""
    if db_type.lower() == "oracle":
        return (
            "You are DeedsAI, an expert Oracle Database Administrator assistant.\n\n"
            "You have access to a live Oracle database via the OracleQueryAgent tool.\n"
            "When the user asks a database question, use the tool to run SQL and get REAL data.\n\n"
            "RULES:\n"
            "- Always use the OracleQueryAgent tool to get real data before answering\n"
            "- Write PLAIN SQL — no markdown, no backticks, no semicolons\n"
            "- Use Oracle system views: v$session, v$sql, dba_tablespaces, dba_objects, etc.\n"
            "- Present results in clear, plain English with a summary\n"
            "- For complex questions run multiple queries to build a complete picture\n"
            "- ALWAYS run at least 2-3 queries for any performance question\n"
            "- Do not stop after 1 query — investigate thoroughly\n"
            "- Highlight any issues, anomalies, or things that need attention\n\n"
            "⚠️  READ-ONLY / ADVISORY MODE:\n"
            "- The tool only allows SELECT statements — DDL and DML are blocked.\n"
            "- If a change is needed (CREATE INDEX, GATHER STATS, ALTER, etc.), present it\n"
            "  as a recommendation script that the DBA will review and run manually.\n"
            "- Never attempt to execute DDL or DML through the tool.\n\n"
            "CRITICAL TOOL FORMAT:\n"
            "Action: OracleQueryAgent\n"
            "Action Input: SELECT ... FROM ...\n"
        )
    else:
        return (
            "You are DeedsAI, an expert PostgreSQL Database Administrator assistant.\n\n"
            "You have access to a live PostgreSQL database via the PostgresQueryAgent tool.\n"
            "When the user asks a database question, use the tool to run SQL and get REAL data.\n\n"
            "RULES:\n"
            "- Always use the PostgresQueryAgent tool to get real data before answering\n"
            "- Write PLAIN SQL — no markdown, no backticks\n"
            "- Use PostgreSQL system views: pg_stat_activity, pg_stat_database, pg_locks, "
            "pg_stat_user_tables, etc.\n"
            "- Present results in clear, plain English with a summary\n"
            "- For complex questions run multiple queries to build a complete picture\n"
            "- Highlight any issues, anomalies, or things that need attention\n\n"
            "⚠️  READ-ONLY / ADVISORY MODE:\n"
            "- The tool only allows SELECT statements — DDL and DML are blocked.\n"
            "- If a change is needed (CREATE INDEX, VACUUM, ALTER TABLE, etc.), present it\n"
            "  as a recommendation script that the DBA will review and run manually.\n"
            "- Never attempt to execute DDL or DML through the tool.\n\n"
            "CRITICAL TOOL FORMAT:\n"
            "Action: PostgresQueryAgent\n"
            "Action Input: SELECT ... FROM ...\n"
        )


def _check_guardrails(message: str, username: str, db_type: str):
    try:
        from content_filter import validate_chat_question
        ok, msg = validate_chat_question(message)
        if not ok:
            return False, msg, "content_filter"
    except (ImportError, Exception):
        pass
    return True, "", None


def _log_chat(username, question, response, db_type):
    try:
        from activity_logger import log_ai_chat
        from app.api.llm_settings import _get_user_cfg
        cfg = _get_user_cfg(username)
        log_ai_chat(username, question, response,
                    cfg.get("provider", "?"), cfg.get("model", "?"), db_type)
    except Exception:
        pass


# ── Streaming chat ────────────────────────────────────────────────────────────

@ai_bp.post("/chat/stream")
@jwt_required()
def chat_stream():
    if err := _require_ai(): return err

    data     = request.get_json(silent=True) or {}
    message  = (data.get("message") or "").strip()
    db_type  = (data.get("db_type") or "postgres").lower()
    username = get_jwt_identity()
    req_provider = data.get("provider")
    req_model    = data.get("model")

    if not message:
        return Response('data: {"error": "message is required"}\n\n',
                        content_type="text/event-stream")

    # Guardrails run in request context — fine
    ok, block_msg, guardrail = _check_guardrails(message, username, db_type)
    if not ok:
        def _blocked():
            yield f'data: {json.dumps({"error": block_msg, "guardrail": guardrail})}\n\n'
            yield 'data: {"done": true}\n\n'
        return Response(stream_with_context(_blocked()), content_type="text/event-stream")

    # ── Snapshot everything we need BEFORE the generator runs ──────────────
    # This avoids any request-context issues once we're in the generator /
    # background thread.
    try:
        llm = _get_llm(username, req_provider, req_model, streaming=False)
    except Exception as exc:
        def _no_llm(e=exc):
            yield f'data: {json.dumps({"error": f"LLM not configured: {e}. Go to LLM Settings."})}\n\n'
            yield 'data: {"done": true}\n\n'
        return Response(stream_with_context(_no_llm()), content_type="text/event-stream")

    # Capture Flask app so we can push it into the background thread
    app = current_app._get_current_object()

    # Bind all values as default args (evaluated NOW, not when generator runs)
    # and use underscore names throughout to avoid ANY closure/cell variable issues.
    _u   = str(username)
    _dt  = str(db_type)
    _msg = str(message)
    _llm = llm
    _app = current_app._get_current_object()

    def generate(_u=_u, _dt=_dt, _msg=_msg, _llm=_llm, _app=_app) -> Generator[str, None, None]:
        try:
            from langchain.agents import initialize_agent, AgentType
            from langchain.callbacks.base import BaseCallbackHandler
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parents[2]))
            from agent_executor_tools import build_agent_tools

            with _app.app_context():
                all_tools = build_agent_tools(_u)

            if _dt == "oracle":
                agent_tools = [all_tools["OracleQueryAgent"]]
            else:
                agent_tools = [all_tools["PostgresQueryAgent"]]

            class StepCapture(BaseCallbackHandler):
                def __init__(self):
                    self.queue = []

                def on_agent_action(self, action, **kw):
                    self.queue.append({
                        "step": {
                            "type":  "tool_call",
                            "tool":  action.tool,
                            "input": str(action.tool_input)[:300],
                        }
                    })

                def on_tool_end(self, output, **kw):
                    self.queue.append({
                        "step": {
                            "type":    "observation",
                            "content": str(output)[:2000],
                        }
                    })

            capture = StepCapture()

            is_ollama = "ollama" in str(type(_llm)).lower()
            max_iter  = 20 if is_ollama else 10

            agent = initialize_agent(
                agent_tools,
                _llm,
                agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                verbose=False,
                handle_parsing_errors=True,
                max_iterations=max_iter,
                early_stopping_method="generate",
                callbacks=[capture],
                agent_kwargs={"prefix": _ai_system_prompt(_dt)},
            )

            yield f'data: {json.dumps({"status": f"🔍 Querying {_dt.upper()} database…"})}\n\n'

            result_q = qmodule.Queue()

            # run_agent uses only default-arg-bound names — no closures at all
            def run_agent(_a=_app, _d=_dt, _m=_msg, _ag=agent, _q=result_q):
                with _a.app_context():
                    try:
                        ctx_prompt = f"[Database Type: {_d.title()}] {_m}"
                        result = _ag.run(ctx_prompt)
                        _q.put(("done", result))
                    except Exception as exc:
                        _q.put(("error", str(exc)))

            t = threading.Thread(target=run_agent, daemon=True)
            t.start()

            final_answer = ""
            while True:
                while capture.queue:
                    evt = capture.queue.pop(0)
                    yield f"data: {json.dumps(evt)}\n\n"

                try:
                    status, payload = result_q.get_nowait()
                    while capture.queue:
                        evt = capture.queue.pop(0)
                        yield f"data: {json.dumps(evt)}\n\n"

                    if status == "error":
                        yield f'data: {json.dumps({"error": payload})}\n\n'
                    else:
                        final_answer = payload
                        words = final_answer.split(" ")
                        for i in range(0, len(words), 8):
                            chunk = " ".join(words[i:i + 8])
                            if i + 8 < len(words):
                                chunk += " "
                            yield f"data: {json.dumps({'token': chunk})}\n\n"
                    break

                except qmodule.Empty:
                    time.sleep(0.05)
                    continue

            _append_history(_u, "user", _msg)
            _append_history(_u, "assistant", final_answer)
            _log_chat(_u, _msg, final_answer, _dt)
            yield 'data: {"done": true}\n\n'

        except Exception as exc:
            yield f'data: {json.dumps({"error": str(exc)})}\n\n'
            yield 'data: {"done": true}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── History ───────────────────────────────────────────────────────────────────

@ai_bp.get("/chat/history")
@jwt_required()
def get_history():
    if err := _require_ai(): return err
    return jsonify({"history": _history.get(get_jwt_identity(), [])})


@ai_bp.post("/chat/clear")
@jwt_required()
def clear_history():
    if err := _require_ai(): return err
    _history[get_jwt_identity()] = []
    return jsonify({"ok": True})


@ai_bp.get("/providers")
@jwt_required()
def list_providers():
    """Return current provider+model for the logged-in user."""
    try:
        from app.api.llm_settings import _get_user_cfg
        cfg = _get_user_cfg(get_jwt_identity())
        return jsonify({
            "provider": cfg.get("provider", ""),
            "model":    cfg.get("model", ""),
        })
    except Exception as exc:
        return jsonify({"provider": "", "model": "", "error": str(exc)})
