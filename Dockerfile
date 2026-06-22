# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for psycopg2, oracledb, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libffi-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: production image ─────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="Your Name <your-email@example.com>"
LABEL description="dbadeeds.ai — AI Database Intelligence Platform"
LABEL version="3.1"

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r dbai && useradd -r -g dbai -d /app dbai

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=dbai:dbai . .

# Copy existing backend modules from Streamlit app (mounted or baked in)
# COPY --chown=dbai:dbai ../dbadeedsai_v3_1/db_manager.py .
# COPY --chown=dbai:dbai ../dbadeedsai_v3_1/sql_safety.py .
# COPY --chown=dbai:dbai ../dbadeedsai_v3_1/user_management.py .
# COPY --chown=dbai:dbai ../dbadeedsai_v3_1/content_filter.py .

# Create data directory for JSON stores
RUN mkdir -p /app/data && chown dbai:dbai /app/data

USER dbai

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/auth/me')" || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:application"]
