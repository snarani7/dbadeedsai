"""
run_ssl.py — Windows HTTPS launcher for dbadeeds.ai (Python 3.12 compatible)

ssl.wrap_socket() was removed in Python 3.12.
This uses SSLContext.wrap_socket() which works on 3.10, 3.11, 3.12+.

Usage:
    python run_ssl.py
"""

import ssl
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Cert paths ────────────────────────────────────────────────────────────────
_CERT_DIR = Path(r"C:\dbadeedsai\certs")

def _find(name: str) -> Path:
    """Return the cert file trying bare name then common extensions."""
    base = _CERT_DIR / name
    if base.exists():
        return base
    for ext in (".cer", ".crt", ".pem"):
        p = _CERT_DIR / (name + ext)
        if p.exists():
            return p
    # List directory to help debug
    files = [f.name for f in _CERT_DIR.iterdir()] if _CERT_DIR.exists() else ["<dir not found>"]
    raise FileNotFoundError(
        f"Cannot find '{name}' in {_CERT_DIR}\n"
        f"Files present: {files}"
    )

CERT_FILE = _find("chain")      # chain.cer or chain
KEY_FILE  = _find("server.key") # server.key
PORT      = int(os.getenv("PORT", "8080"))

print(f"\n  🔒 dbadeeds.ai — HTTPS (Python 3.12)")
print(f"  🌐 https://0.0.0.0:{PORT}")
print(f"  📜 Cert : {CERT_FILE}")
print(f"  🔑 Key  : {KEY_FILE}\n")

# ── App ───────────────────────────────────────────────────────────────────────
from app import create_app
from waitress import create_server

app = create_app()

# ── SSL context (Python 3.12 way) ─────────────────────────────────────────────
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))

# Optional: restrict to TLS 1.2+ only (recommended)
ctx.minimum_version = ssl.TLSVersion.TLSv1_2

# ── Create Waitress server then wrap its socket ───────────────────────────────
server = create_server(
    app,
    host            = "0.0.0.0",
    port            = PORT,
    threads         = 8,
    channel_timeout = 120,
    url_scheme      = "https",
)

# Wrap with SSL context — this is the Python 3.12 compatible method
server.socket = ctx.wrap_socket(
    server.socket,
    server_side = True,
)

print(f"  ✅ SSL active — listening on https://0.0.0.0:{PORT}\n")
print(f"  Access via:")
print(f"    https://localhost:{PORT}")
print(f"    https://10.177.153.108:{PORT}\n")

server.run()