"""
gunicorn.conf.py — Gunicorn production configuration.
This is the Python equivalent of a Tomcat server.xml.

Run: gunicorn --config gunicorn.conf.py wsgi:application
"""

import multiprocessing
import os

# ── Binding ───────────────────────────────────────────────────────────────────
bind       = f"0.0.0.0:{os.getenv('PORT', '5000')}"
backlog    = 2048

# ── Workers ───────────────────────────────────────────────────────────────────
# gevent workers handle concurrent requests (streaming AI, DB queries)
# without spawning a thread per request
worker_class   = "gevent"
workers        = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_connections = 1000   # max concurrent connections per worker
threads        = 1           # gevent handles concurrency via greenlets

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout        = 120    # 2 min — accommodates slow LLM calls
keepalive      = 5
graceful_timeout = 30   # worker shutdown grace period

# ── Logging ───────────────────────────────────────────────────────────────────
loglevel       = os.getenv("LOG_LEVEL", "info")
accesslog      = "-"    # stdout — captured by Docker/systemd
errorlog       = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" %(D)sµs'

# ── Process ───────────────────────────────────────────────────────────────────
proc_name      = "dbadeedsai"
daemon         = False   # systemd/Docker manage the process
pidfile        = None

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line   = 8190
limit_request_fields = 200

# Add these lines to gunicorn.conf.py:

CERT_DIR = "C:\\dbadeedsai\\certs\\"

certfile = f"{CERT_DIR}chain.cer"    # full chain (server + root CA)
keyfile  = f"{CERT_DIR}server.key"   # private key
bind     = f"0.0.0.0:{os.getenv('PORT', '8080')}"  # use 8443 for HTTPS

# ── Hooks ─────────────────────────────────────────────────────────────────────
def on_starting(server):
    server.log.info("🚀 dbadeeds.ai starting — workers: %d, bind: %s", workers, bind)

def worker_exit(server, worker):
    server.log.info("Worker %d exited", worker.pid)
