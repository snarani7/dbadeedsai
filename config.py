"""
config.py — dbadeeds.ai Flask Configuration

Python 3.14 features used:
  • @dataclass(slots=True, frozen=True)  — zero-overhead, immutable config
  • pathlib.Path                         — replaces all os.path juggling
  • X | None union syntax               — no more Optional[X]
  • type keyword for aliases            — PEP 695 (3.12+)
  • match/case                          — selects environment variant
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path


# ── PEP 695 type aliases ───────────────────────────────────────────────────────
type OriginList = list[str]


# ── Helpers ────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.resolve()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _data(filename: str) -> str:
    """Resolve data-file path, honouring env override."""
    if override := _env(filename.upper().replace(".", "_").replace("-", "_")):
        return override
    return str(_REPO_ROOT / "data" / filename)


# ── Base config dataclass ──────────────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class _BaseConfig:
    # Security
    SECRET_KEY:    str = field(default_factory=lambda: _env("SECRET_KEY") or secrets.token_hex(32))
    JWT_SECRET_KEY: str = field(default_factory=lambda: _env("JWT_SECRET_KEY") or secrets.token_hex(32))

    # JWT
    JWT_TOKEN_LOCATION:        list[str]  = field(default_factory=lambda: ["cookies", "headers"])
    JWT_ACCESS_TOKEN_EXPIRES:  timedelta  = field(default_factory=lambda: timedelta(minutes=30))
    JWT_REFRESH_TOKEN_EXPIRES: timedelta  = field(default_factory=lambda: timedelta(days=7))
    JWT_COOKIE_CSRF_PROTECT:   bool       = False
    JWT_COOKIE_SECURE:         bool       = False

    # CORS
    CORS_ORIGINS: OriginList = field(
        default_factory=lambda: _env("CORS_ORIGINS", "*").split(",")
    )

    # Rate limiting
    RATELIMIT_STORAGE_URI: str = field(default_factory=lambda: _env("REDIS_URL", "memory://"))
    RATELIMIT_DEFAULT:     str = "200 per minute"

    # Data file paths (shared with legacy Streamlit modules)
    DB_CONNECTIONS_FILE: str = field(default_factory=lambda: _env("DB_CONNECTIONS_FILE") or _data("db_connections.json"))
    USERS_FILE:          str = field(default_factory=lambda: _env("USERS_FILE")          or _data("users.json"))
    LLM_CONFIG_FILE:     str = field(default_factory=lambda: _env("LLM_CONFIG_FILE")     or _data("llm_config.json"))

    # Legacy module base directory
    BASE_DIR: str = field(default_factory=lambda: str(_REPO_ROOT))

    # LLM defaults
    DEFAULT_LLM_PROVIDER: str = field(default_factory=lambda: _env("DEFAULT_LLM_PROVIDER", "openai"))
    DEFAULT_LLM_MODEL:    str = field(default_factory=lambda: _env("DEFAULT_LLM_MODEL",    "gpt-4o-mini"))

    # Database API Key (optional)
    # COPS_API_KEY: str = field(default_factory=lambda: _env("COPS_API_KEY"))

    # Logging
    LOG_LEVEL: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())

    # Debug (overridden per environment)
    DEBUG: bool = False


@dataclass(slots=True, frozen=True)
class DevelopmentConfig(_BaseConfig):
    DEBUG:             bool = True
    JWT_COOKIE_SECURE: bool = False


@dataclass(slots=True, frozen=True)
class ProductionConfig(_BaseConfig):
    DEBUG:             bool = False
    JWT_COOKIE_SECURE: bool = True


# ── Factory ────────────────────────────────────────────────────────────────────

def get_config() -> DevelopmentConfig | ProductionConfig:
    """Select config class based on FLASK_ENV using match/case."""
    match _env("FLASK_ENV", "development").lower():
        case "production" | "prod":
            return ProductionConfig()
        case _:
            return DevelopmentConfig()
