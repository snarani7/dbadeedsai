"""
app/api/llm_settings.py — LLM provider configuration endpoints.

Mirrors the Streamlit LLM Settings page:
  - Multi-user config stored per-user in data/llm_config.json
  - Supports: OpenAI, Anthropic, Google Gemini, Vertex AI, Groq, Ollama
  - Tests connectivity before saving
  - Admin can view/override all users

Routes:
  GET    /api/llm/config           → get my config
  POST   /api/llm/config           → save my config
  POST   /api/llm/test             → test a provider (no save)
  GET    /api/llm/providers        → available providers + models
  GET    /api/llm/config/<user>    → admin: get user config
"""

from __future__ import annotations

import json
import os
from datetime import datetime, UTC
from pathlib import Path

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from activity_logger import log_llm_config_change, log_activity

llm_settings_bp = Blueprint("llm_settings", __name__)


# ── Provider catalogue ─────────────────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
    "openai": {
        "label":    "OpenAI",
        "icon":     "🟢",
        "models":   ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "requires": ["OPENAI_API_KEY"],
        "auth":     "api_key",
    },
    "anthropic": {
        "label":    "Anthropic Claude",
        "icon":     "🟠",
        "models":   ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "requires": ["ANTHROPIC_API_KEY"],
        "auth":     "api_key",
    },
    "gemini": {
        "label":    "Google Gemini",
        "icon":     "🔵",
        "models":   ["gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-1.5-pro", "gemini-1.5-flash"],
        "requires": ["GOOGLE_API_KEY"],
        "auth":     "api_key",
    },
    "vertexai": {  # gemini-2.0-flash-exp removed (deprecated); use gemini-2.0-flash or gemini-1.5-pro
        "label":    "Google Vertex AI",
        "icon":     "☁️",
        "models":   ["gemini-2.0-flash-001", "gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-1.5-pro-002", "gemini-1.5-pro", "gemini-1.5-flash-002", "gemini-1.5-flash", "gemini-1.0-pro-002"],
        "requires": ["GOOGLE_APPLICATION_CREDENTIALS or gcloud auth"],
        "auth":     "vertex",
    },
    "groq": {
        "label":    "Groq",
        "icon":     "⚡",
        "models":   ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        "requires": ["GROQ_API_KEY"],
        "auth":     "api_key",
    },
    "ollama": {
        "label":    "Ollama (Local)",
        "icon":     "🦙",
        "models":   ["qwen3-coder:30b", "qwen3-coder:14b", "llama3.3", "llama3.2", "llama3.1",
                     "mistral", "codellama", "phi3", "qwen2.5", "deepseek-r1"],
        "requires": ["Local Ollama server"],
        "auth":     "none",
    },
    "azure": {
        "label":    "Azure OpenAI",
        "icon":     "🔷",
        "models":   ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-35-turbo"],
        "requires": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        "auth":     "api_key",
    },
    "together": {
        "label":    "Together AI",
        "icon":     "🤝",
        "models":   ["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                     "mistralai/Mixtral-8x7B-Instruct-v0.1",
                     "Qwen/Qwen2.5-72B-Instruct-Turbo"],
        "requires": ["TOGETHER_API_KEY"],
        "auth":     "api_key",
    },
}


# ── Config file helpers ────────────────────────────────────────────────────────

def _cfg_path() -> Path:
    """Always return an absolute path — never relative to unknown CWD.
    Safe to call from background threads (no hard current_app dependency).
    """
    raw = os.getenv("LLM_CONFIG_FILE")
    if not raw:
        try:
            from flask import has_app_context
            if has_app_context():
                raw = current_app.config.get("LLM_CONFIG_FILE")
        except Exception:
            pass
    if raw:
        p = Path(raw)
    else:
        # <repo_root>/data/llm_config.json  (same logic as config.py _data())
        # parents[2] = final_flask/  (app/api/llm_settings.py → app/api → app → final_flask)
        repo_root = Path(__file__).resolve().parents[2]
        p = repo_root / "data" / "llm_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cfg() -> dict[str, dict]:
    p = _cfg_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("llm_config read error %s: %s", p, e)
    return {}


def _save_cfg(cfg: dict[str, dict]) -> None:
    _cfg_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _get_user_cfg(username: str) -> dict:
    """Return user's LLM config, falling back to 'admin' config, then defaults."""
    cfg = _load_cfg()
    if username in cfg:
        return cfg[username]
    if "admin" in cfg:
        return cfg["admin"]
    # Defaults from env
    return {
        "provider": os.getenv("DEFAULT_LLM_PROVIDER", "openai"),
        "model":    os.getenv("DEFAULT_LLM_MODEL",    "gpt-4o-mini"),
        "api_key":  "",
    }


# ── LLM builder (supports all providers) ──────────────────────────────────────

def build_llm(cfg: dict, streaming: bool = False):
    """
    Build a LangChain chat model from a config dict.

    cfg keys: provider, model, api_key, vertexai_project, vertexai_location,
              ollama_base_url
    """
    provider  = cfg.get("provider", "openai")
    model     = cfg.get("model", "gpt-4o-mini")
    api_key   = cfg.get("api_key", "")

    match provider:
        case "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
                streaming=streaming,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model,
                api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""),
                streaming=streaming,
            )
        case "gemini" | "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=api_key or os.getenv("GOOGLE_API_KEY", ""),
                streaming=streaming,
            )
        case "vertexai" | "vertex":
            from langchain_google_vertexai import ChatVertexAI
            project  = cfg.get("vertexai_project")  or os.getenv("VERTEXAI_PROJECT", "")
            location = cfg.get("vertexai_location") or os.getenv("VERTEXAI_LOCATION", "us-central1")
            return ChatVertexAI(
                model=model,
                project=project,
                location=location,
                streaming=streaming,
            )
        case "groq":
            from langchain_groq import ChatGroq
            return ChatGroq(
                model=model,
                api_key=api_key or os.getenv("GROQ_API_KEY", ""),
            )
        case "ollama":
            from langchain_ollama import ChatOllama
            base_url = cfg.get("ollama_base_url") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            return ChatOllama(model=model, base_url=base_url)
        case "azure":
            from langchain_openai import AzureChatOpenAI
            endpoint = cfg.get("azure_endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT", "")
            api_ver  = cfg.get("azure_api_version") or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
            return AzureChatOpenAI(
                azure_endpoint=endpoint,
                azure_deployment=model,
                api_key=api_key or os.getenv("AZURE_OPENAI_API_KEY", ""),
                api_version=api_ver,
                streaming=streaming,
            )
        case "together":
            from langchain_openai import ChatOpenAI
            together_key = api_key or os.getenv("TOGETHER_API_KEY", "")
            return ChatOpenAI(
                model=model, api_key=together_key,
                base_url="https://api.together.xyz/v1",
                streaming=streaming,
            )
        case _:
            raise ValueError(f"Unsupported provider: {provider!r}")


# ── Routes ─────────────────────────────────────────────────────────────────────

@llm_settings_bp.get("/config")
@jwt_required()
def get_config():
    username = get_jwt_identity()
    cfg = _get_user_cfg(username)
    # Never return the raw api_key — mask it
    safe = {k: v for k, v in cfg.items()}
    if "api_key" in safe and safe["api_key"]:
        safe["api_key"] = "****" + safe["api_key"][-4:] if len(safe["api_key"]) > 4 else "****"
    safe["has_key"] = bool(cfg.get("api_key"))
    return jsonify({"config": safe, "providers": PROVIDERS}), 200


@llm_settings_bp.post("/config")
@jwt_required()
def save_config():
    username = get_jwt_identity()
    data     = request.get_json(silent=True) or {}

    provider = data.get("provider", "openai")
    model    = data.get("model", "")
    api_key  = data.get("api_key", "")

    if provider not in PROVIDERS:
        return jsonify({"error": f"Unknown provider: {provider!r}"}), 400
    if not model:
        return jsonify({"error": "model is required"}), 400

    # If api_key is "****...", keep existing key
    cfg = _load_cfg()
    old_cfg = cfg.get(username, {})
    if api_key.startswith("****"):
        api_key = old_cfg.get("api_key", "")

    old_provider = old_cfg.get("provider", "—")
    old_model    = old_cfg.get("model",    "—")

    new_cfg: dict = {
        "provider":     provider,
        "model":        model,
        "api_key":      api_key,
        "last_updated": datetime.now(UTC).isoformat(),
    }

    # Vertex-specific fields
    if provider in ("vertexai", "vertex"):
        new_cfg["vertexai_project"]  = data.get("vertexai_project",  os.getenv("VERTEXAI_PROJECT", ""))
        new_cfg["vertexai_location"] = data.get("vertexai_location", os.getenv("VERTEXAI_LOCATION", "us-central1"))

    # Ollama-specific
    if provider == "ollama":
        new_cfg["ollama_base_url"] = data.get("ollama_base_url", "http://localhost:11434")

    cfg[username] = new_cfg
    _save_cfg(cfg)

    log_llm_config_change(username, old_provider, provider, old_model, model)
    return jsonify({"message": "LLM configuration saved",
                    "provider": provider, "model": model}), 200


@llm_settings_bp.post("/test")
@jwt_required()
def test_provider():
    """Test a provider/model without saving."""
    username = get_jwt_identity()
    data     = request.get_json(silent=True) or {}
    cfg      = {
        "provider":          data.get("provider", "openai"),
        "model":             data.get("model", ""),
        "api_key":           data.get("api_key", ""),
        "vertexai_project":  data.get("vertexai_project", ""),
        "vertexai_location": data.get("vertexai_location", "us-central1"),
        "ollama_base_url":   data.get("ollama_base_url", "http://localhost:11434"),
    }
    # Restore masked key
    if cfg["api_key"].startswith("****"):
        stored = _load_cfg().get(username, {})
        cfg["api_key"] = stored.get("api_key", "")

    try:
        from langchain.schema import HumanMessage
        llm   = build_llm(cfg, streaming=False)
        reply = llm.invoke([HumanMessage(content="Respond with exactly: OK")])
        text  = reply.content if hasattr(reply, "content") else str(reply)
        return jsonify({"ok": True, "response": text[:200]}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200


@llm_settings_bp.get("/providers")
@jwt_required()
def list_providers():
    return jsonify({"providers": PROVIDERS}), 200


@llm_settings_bp.get("/config/<target_user>")
@jwt_required()
def get_user_config(target_user: str):
    """Admin: get another user's config."""
    if "user_management" not in get_jwt().get("permissions", []):
        return jsonify({"error": "Admin required"}), 403
    cfg  = _load_cfg().get(target_user, {})
    safe = {k: v for k, v in cfg.items()}
    if "api_key" in safe and safe["api_key"]:
        safe["api_key"] = "****" + safe["api_key"][-4:]
    return jsonify({"username": target_user, "config": safe}), 200
