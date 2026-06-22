"""
wsgi.py — Production entry point for Gunicorn / Waitress.

Python 3.14 features used:
  • pathlib.Path  — tidy .env resolution
  • match/case    — port/debug selection
  • X | None      — type hints
  • walrus :=     — inline env reads

Usage:
    # Development
    python wsgi.py

    # Production — Gunicorn (Linux)
    gunicorn --config gunicorn.conf.py wsgi:application

    # Production — Waitress (Windows)
    waitress-serve --host=0.0.0.0 --port=5000 --threads=8 wsgi:application
"""

from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root before any config import
load_dotenv(Path(__file__).parent / ".env")

from app import create_app  # noqa: E402  (must follow load_dotenv)

application = create_app()   # Gunicorn looks for 'application' by default


if __name__ == "__main__":
    import os

    port  = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_ENV", "development").lower() != "production"

    match debug:
        case True:
            print(f"  🛠  Development server  →  http://localhost:{port}")
        case False:
            print(f"  🚀  Production mode      →  http://0.0.0.0:{port}")

    application.run(host="0.0.0.0", port=port, debug=debug, threaded=True)


