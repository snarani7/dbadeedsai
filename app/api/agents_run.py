"""
app/api/agents_run.py — AI Agents backend.

Mirrors Streamlit's AI Agents page exactly:
  - Tab 1 (Agent Library):  GET  /api/agents/templates
                            GET  /api/agents/deployed
                            POST /api/agents/deploy
                            DELETE /api/agents/delete/<name>
  - Tab 2 (Create Agent):   POST /api/agents/create
  - Tab 3 (Run Agent):      POST /api/agents/run/stream  (SSE)
                            POST /api/agents/run          (blocking, for scheduler)
  - Tab 4 (Playbooks):      GET  /api/agents/playbooks
                            POST /api/agents/playbooks/run (SSE)
"""
from __future__ import annotations

import json
import sys
from collections.abc import Generator
from pathlib import Path

from flask import Blueprint, request, jsonify, Response, stream_with_context
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

agents_run_bp = Blueprint("agents_run", __name__)

sys.path.insert(0, str(Path(__file__).parents[2]))  # → final_flask/


def _require_perm():
    if "ai_agents" not in get_jwt().get("permissions", []):
        return jsonify({"error": "ai_agents permission required"}), 403


def _get_tools_and_llm(username: str):
    from agent_executor_tools import build_agent_tools
    from app.api.ai import _get_llm
    tools = build_agent_tools(username)
    llm   = _get_llm(username)
    return tools, llm


# ── Templates ─────────────────────────────────────────────────────────────────

@agents_run_bp.get("/templates")
@jwt_required()
def list_templates():
    if err := _require_perm(): return err
    from agent_executor_tools import AgentTemplates
    out = []
    for t in AgentTemplates.get_all_templates():
        out.append({
            "name":          t.name,
            "agent_type":    t.agent_type.value,
            "database_type": t.database_type.value,
            "description":   t.description,
            "tools":         t.tools,
            "temperature":   t.temperature,
            "system_prompt": t.system_prompt,
        })
    return jsonify({"templates": out})


# ── Deployed agents ────────────────────────────────────────────────────────────

@agents_run_bp.get("/deployed")
@jwt_required()
def list_deployed():
    if err := _require_perm(): return err
    from agent_executor_tools import AgentManager
    mgr = AgentManager()
    agents = []
    for name in mgr.list_agents():
        ag = mgr.load_agent(name)
        if ag:
            agents.append({
                "name":          ag.name,
                "agent_type":    ag.agent_type.value,
                "database_type": ag.database_type.value,
                "description":   ag.description,
                "tools":         ag.tools,
                "temperature":   ag.temperature,
                "model":         ag.model,
                "max_iterations": ag.max_iterations,
                "system_prompt": ag.system_prompt,
            })
    return jsonify({"agents": agents})


@agents_run_bp.post("/deploy")
@jwt_required()
def deploy_template():
    """Deploy a built-in template by name — same as Streamlit 'Deploy' button."""
    if err := _require_perm(): return err
    data          = request.get_json(silent=True) or {}
    template_name = data.get("template_name", "")
    from agent_executor_tools import AgentTemplates, AgentManager
    match = [t for t in AgentTemplates.get_all_templates() if t.name == template_name]
    if not match:
        return jsonify({"error": f"Template '{template_name}' not found"}), 404
    mgr = AgentManager()
    ok  = mgr.save_agent(match[0])
    return jsonify({"ok": ok, "name": template_name})


@agents_run_bp.delete("/delete/<path:agent_name>")
@jwt_required()
def delete_agent(agent_name: str):
    if err := _require_perm(): return err
    from agent_executor_tools import AgentManager
    ok = AgentManager().delete_agent(agent_name)
    return jsonify({"ok": ok})


# ── Create custom agent ────────────────────────────────────────────────────────

@agents_run_bp.post("/create")
@jwt_required()
def create_agent():
    """Create a custom agent — same as Streamlit Tab 2 form."""
    if err := _require_perm(): return err
    data = request.get_json(silent=True) or {}
    from agent_executor_tools import AgentConfig, AgentType, DatabaseType, AgentManager
    required = ["name", "agent_type", "database_type", "description", "system_prompt", "tools"]
    missing  = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    try:
        ag = AgentConfig(
            name          = data["name"],
            agent_type    = AgentType(data["agent_type"]),
            database_type = DatabaseType(data["database_type"]),
            description   = data["description"],
            system_prompt = data["system_prompt"],
            tools         = data["tools"],
            temperature   = float(data.get("temperature", 0.0)),
            model         = data.get("model", "gpt-4o"),
            max_iterations= int(data.get("max_iterations", 10)),
        )
        ok = AgentManager().save_agent(ag)
        return jsonify({"ok": ok, "name": ag.name})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Run agent — SSE streaming (Tab 3) ─────────────────────────────────────────

@agents_run_bp.post("/run/stream")
@jwt_required()
def run_stream():
    if err := _require_perm(): return err

    data       = request.get_json(silent=True) or {}
    agent_name = (data.get("agent_name") or "").strip()
    message    = (data.get("message") or "").strip()
    username   = get_jwt_identity()

    if not agent_name or not message:
        def _err():
            yield 'data: {"error": "agent_name and message are required"}\n\n'
            yield 'data: {"done": true}\n\n'
        return Response(stream_with_context(_err()), content_type="text/event-stream")

    # Content filter — same as Streamlit
    try:
        from content_filter import validate_chat_question
        allowed, blk = validate_chat_question(message)
        if not allowed:
            def _blocked():
                yield f'data: {json.dumps({"error": blk, "guardrail": "content_filter"})}\n\n'
                yield 'data: {"done": true}\n\n'
            return Response(stream_with_context(_blocked()), content_type="text/event-stream")
    except ImportError:
        pass

    def generate() -> Generator[str, None, None]:
        try:
            from agent_executor_tools import AgentManager, AgentExecutor
            from langchain.callbacks.base import BaseCallbackHandler

            mgr = AgentManager()
            ag  = mgr.load_agent(agent_name)
            if not ag:
                yield f'data: {json.dumps({"error": f"Agent \'{agent_name}\' not found"})}\n\n'
                yield 'data: {"done": true}\n\n'
                return

            tools, llm = _get_tools_and_llm(username)
            yield f"data: {json.dumps({'status': f'🤖 Running {agent_name}…'})}\n\n"

            # Use AgentExecutor (same class as Streamlit)
            executor = AgentExecutor(llm, tools)
            response = executor.execute_agent(ag, message)

            # Stream the final response token by token (simulate streaming)
            # Streamlit streams via agent.stream() — we emit in chunks
            words = response.split(" ")
            chunk_size = 8
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i+chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield f"data: {json.dumps({'token': chunk})}\n\n"

            try:
                from activity_logger import log_ai_chat
                from app.api.llm_settings import _get_user_cfg
                cfg = _get_user_cfg(username)
                log_ai_chat(username, message, response,
                            cfg.get("provider", "?"), cfg.get("model", "?"),
                            ag.database_type.value)
            except Exception:
                pass

            yield 'data: {"done": true}\n\n'

        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield 'data: {"done": true}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Run agent — blocking (used by agent scheduler) ────────────────────────────

@agents_run_bp.post("/run")
@jwt_required()
def run_blocking():
    if err := _require_perm(): return err
    data       = request.get_json(silent=True) or {}
    agent_name = (data.get("agent_name") or "").strip()
    message    = (data.get("message") or "").strip()
    username   = get_jwt_identity()
    if not agent_name or not message:
        return jsonify({"error": "agent_name and message required"}), 400

    try:
        from agent_executor_tools import AgentManager, AgentExecutor
        mgr = AgentManager()
        ag  = mgr.load_agent(agent_name)
        if not ag:
            return jsonify({"error": f"Agent '{agent_name}' not found"}), 404
        tools, llm = _get_tools_and_llm(username)
        executor   = AgentExecutor(llm, tools)
        response   = executor.execute_agent(ag, message)
        return jsonify({"response": response, "agent": agent_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Playbooks ─────────────────────────────────────────────────────────────────

@agents_run_bp.get("/playbooks")
@jwt_required()
def list_playbooks():
    if err := _require_perm(): return err
    from agent_executor_tools import AGENT_PLAYBOOKS
    out = {}
    for name, pb in AGENT_PLAYBOOKS.items():
        out[name] = {
            "agent_type":    pb["agent_type"].value,
            "database_type": pb["database_type"].value,
            "queries":       pb["queries"],
        }
    return jsonify({"playbooks": out})


@agents_run_bp.post("/playbooks/run")
@jwt_required()
def run_playbook():
    """
    Run a playbook — streams progress events.
    Mirrors Streamlit Tab 4: iterates queries, shows progress bar.
    """
    if err := _require_perm(): return err

    data     = request.get_json(silent=True) or {}
    pb_name  = (data.get("playbook_name") or "").strip()
    username = get_jwt_identity()

    if not pb_name:
        def _err():
            yield 'data: {"error": "playbook_name is required"}\n\n'
            yield 'data: {"done": true}\n\n'
        return Response(stream_with_context(_err()), content_type="text/event-stream")

    def generate() -> Generator[str, None, None]:
        try:
            from agent_executor_tools import (
                AGENT_PLAYBOOKS, AgentTemplates, AgentExecutor, build_agent_tools
            )
            from app.api.ai import _get_llm

            pb = AGENT_PLAYBOOKS.get(pb_name)
            if not pb:
                yield f'data: {json.dumps({"error": f"Playbook \'{pb_name}\' not found"})}\n\n'
                yield 'data: {"done": true}\n\n'
                return

            # Find matching template — same logic as Streamlit
            matches = [
                t for t in AgentTemplates.get_all_templates()
                if t.agent_type == pb["agent_type"]
                and t.database_type == pb["database_type"]
            ]
            if not matches:
                yield f'data: {json.dumps({"error": "No matching agent template found for this playbook."})}\n\n'
                yield 'data: {"done": true}\n\n'
                return

            pb_agent = matches[0]
            tools    = build_agent_tools(username)
            llm      = _get_llm(username)
            executor = AgentExecutor(llm, tools)

            queries = pb["queries"]
            total   = len(queries)

            yield f"data: {json.dumps({'playbook_start': {'name': pb_name, 'total': total}})}\n\n"

            results = []
            for i, query in enumerate(queries, 1):
                yield f"data: {json.dumps({'progress': {'current': i, 'total': total, 'query': query}})}\n\n"
                result = executor.execute_agent(pb_agent, query)
                results.append({"query": query, "result": result})
                yield f"data: {json.dumps({'check_result': {'index': i, 'query': query, 'result': result}})}\n\n"

            yield f"data: {json.dumps({'playbook_done': {'name': pb_name, 'results': results}})}\n\n"
            yield 'data: {"done": true}\n\n'

        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield 'data: {"done": true}\n\n'

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Agent Scheduler REST API  (consumed by Agent Monitor page)
#  All routes: /api/agents/schedules/*
# ══════════════════════════════════════════════════════════════════════════════

@agents_run_bp.get("/schedules")
@jwt_required()
def list_schedules_api():
    """List all schedules with last-run status."""
    if err := _require_perm(): return err
    from agent_scheduler import list_schedules, get_run_history
    schedules = list_schedules()
    # Attach most-recent run to each schedule
    for s in schedules:
        recent = get_run_history(s["id"], limit=1)
        s["last_run_record"] = recent[0] if recent else None
    return jsonify({"schedules": schedules})


@agents_run_bp.post("/schedules")
@jwt_required()
def create_schedule_api():
    """Create a new agent schedule."""
    if err := _require_perm(): return err
    data = request.get_json(silent=True) or {}
    username = get_jwt_identity()
    required = ["name", "db_type", "task", "frequency"]
    missing  = [k for k in required if not data.get(k)]
    # agent_type can come from template_name
    if not data.get("agent_type") and not data.get("template_name"):
        missing.append("agent_type (or template_name)")
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    # Default agent_type from template if not provided
    if not data.get("agent_type") and data.get("template_name"):
        data["agent_type"] = "performance"   # will be overridden by template at runtime
    from agent_scheduler import create_schedule
    s = create_schedule(data, created_by=username)
    return jsonify({"ok": True, "schedule": s}), 201


@agents_run_bp.put("/schedules/<schedule_id>")
@jwt_required()
def update_schedule_api(schedule_id: str):
    if err := _require_perm(): return err
    data = request.get_json(silent=True) or {}
    from agent_scheduler import update_schedule
    s = update_schedule(schedule_id, data)
    if not s:
        return jsonify({"error": "Schedule not found"}), 404
    return jsonify({"ok": True, "schedule": s})


@agents_run_bp.delete("/schedules/<schedule_id>")
@jwt_required()
def delete_schedule_api(schedule_id: str):
    if err := _require_perm(): return err
    from agent_scheduler import delete_schedule
    ok = delete_schedule(schedule_id)
    return jsonify({"ok": ok}) if ok else (jsonify({"error": "Not found"}), 404)


@agents_run_bp.post("/schedules/<schedule_id>/toggle")
@jwt_required()
def toggle_schedule_api(schedule_id: str):
    if err := _require_perm(): return err
    from agent_scheduler import toggle_schedule
    s = toggle_schedule(schedule_id)
    if not s:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True, "schedule": s})


@agents_run_bp.post("/schedules/<schedule_id>/run-now")
@jwt_required()
def run_schedule_now_api(schedule_id: str):
    """Trigger a schedule immediately (manual run)."""
    if err := _require_perm(): return err
    username = get_jwt_identity()
    from agent_scheduler import run_agent_now
    run = run_agent_now(schedule_id, triggered_by=f"manual:{username}")
    if "error" in run:
        return jsonify({"error": run["error"]}), 400
    return jsonify({"ok": True, "run": run})


@agents_run_bp.get("/schedules/history")
@jwt_required()
def get_all_history():
    """Get run history across all schedules."""
    if err := _require_perm(): return err
    limit       = int(request.args.get("limit", 50))
    schedule_id = request.args.get("schedule_id")
    from agent_scheduler import get_run_history
    runs = get_run_history(schedule_id=schedule_id, limit=limit)
    return jsonify({"runs": runs})
