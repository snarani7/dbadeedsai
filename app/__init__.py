"""
app/__init__.py — Flask application factory for dbadeeds.ai
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_swagger_ui import get_swaggerui_blueprint

from config import get_config, DevelopmentConfig, ProductionConfig

jwt     = JWTManager()
limiter = Limiter(key_func=get_remote_address)


def create_app(config_object: DevelopmentConfig | ProductionConfig | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    cfg = config_object or get_config()
    app.config.from_object(cfg)

    # Ensure data + logs dirs exist
    Path(cfg.BASE_DIR, "data").mkdir(parents=True, exist_ok=True)
    Path(cfg.BASE_DIR, "logs").mkdir(parents=True, exist_ok=True)

    # Extensions
    jwt.init_app(app)
    limiter.init_app(app)
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    # JWT error handlers
    @jwt.expired_token_loader
    def expired_token(_h, _p):
        return jsonify({"error": "Token has expired", "code": "TOKEN_EXPIRED"}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify({"error": "Invalid token", "reason": reason}), 401

    @jwt.unauthorized_loader
    def missing_token(reason):
        return jsonify({"error": "Authorisation required", "reason": reason}), 401

    # API blueprints
    from app.api.auth         import auth_bp
    from app.api.users        import users_bp
    from app.api.connections  import connections_bp
    from app.api.query        import query_bp
    from app.api.ai           import ai_bp
    from app.api.llm_settings import llm_settings_bp
    from app.api.playbooks    import playbooks_bp
    from app.api.logs         import logs_bp
    from app.api.guardrails   import guardrails_bp
    from app.api.agents       import agents_bp
    from app.api.agents_run   import agents_run_bp
    from app.web                  import web_bp
    from app.api.notifications    import notifications_bp
    #from app.api.mcp_console      import mcp_console_bp

    app.register_blueprint(auth_bp,         url_prefix="/api/auth")
    app.register_blueprint(users_bp,        url_prefix="/api/users")
    app.register_blueprint(connections_bp,  url_prefix="/api/connections")
    app.register_blueprint(query_bp,        url_prefix="/api/query")
    app.register_blueprint(ai_bp,           url_prefix="/api/ai")
    app.register_blueprint(llm_settings_bp, url_prefix="/api/llm")
    app.register_blueprint(playbooks_bp,    url_prefix="/api/playbooks")
    app.register_blueprint(logs_bp,         url_prefix="/api/logs")
    app.register_blueprint(guardrails_bp,   url_prefix="/api/guardrails")
    app.register_blueprint(agents_bp,       url_prefix="/api/agents")
    app.register_blueprint(agents_run_bp,   url_prefix="/api/agents")
    app.register_blueprint(notifications_bp,  url_prefix="/api/notifications")
    #app.register_blueprint(mcp_console_bp,    url_prefix="/api/mcp")
    app.register_blueprint(web_bp)

    # Start background agent scheduler (APScheduler)
    from agent_scheduler import start_scheduler
    start_scheduler(app)

    # Swagger
    app.register_blueprint(
        get_swaggerui_blueprint("/api/docs", "/static/openapi.json",
                                config={"app_name": "dbadeeds.ai API"}),
        url_prefix="/api/docs",
    )

    # Global error handlers
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Unhandled exception")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(429)
    def ratelimit_handler(e):
        return jsonify({"error": "Rate limit exceeded", "retry_after": str(e.description)}), 429

    return app
