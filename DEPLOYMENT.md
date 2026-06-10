# dbadeeds.ai — Production Deployment Guide

## Architecture Overview

```
Browser / API clients
        │
        ▼
    [Nginx]                 ← SSL termination, static files, rate limiting
    Port 80/443             ← (equivalent to Apache/Tomcat's HTTP connector)
        │
        ▼
   [Gunicorn]              ← Python WSGI server (replaces Tomcat)
   Port 5000 (internal)    ← gevent workers handle concurrent AI/DB requests
        │
        ▼
   [Flask App]             ← Your application code
        │
        ├── [Redis]        ← Rate limiting, session cache
        ├── [users.json]   ← User store (upgrade to PostgreSQL for scale)
        └── [db_connections.json]
```

**Tomcat → Python equivalent:**
| Java stack    | Python stack   | Role                            |
|---------------|----------------|---------------------------------|
| Tomcat        | Gunicorn       | WSGI/servlet container          |
| Apache httpd  | Nginx          | Reverse proxy, SSL, static files|
| WAR file      | Python package | Application                     |
| web.xml       | config.py      | Server configuration            |
| JNDI datasource| connection pool| DB connection management        |

---

## Quick Start (Docker — recommended)

### 1. Prerequisites
```bash
# Install Docker and Docker Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### 2. Clone / copy your project
```bash
mkdir -p /opt/dbadeedsai
cd /opt/dbadeedsai
# Copy flask_app/ contents here
# Copy your existing Streamlit modules alongside:
cp /path/to/dbadeedsai_v3_1/sql_safety.py      .
cp /path/to/dbadeedsai_v3_1/user_management.py .
cp /path/to/dbadeedsai_v3_1/content_filter.py  .
cp /path/to/dbadeedsai_v3_1/db_manager.py      .
```

### 3. Configure environment
```bash
cp .env.example .env
nano .env   # Fill in SECRET_KEY, JWT_SECRET_KEY, API keys
```

Generate strong keys:
```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"
```

### 4. SSL certificates
```bash
mkdir -p nginx/ssl

# Option A: Let's Encrypt (production)
sudo apt install certbot
sudo certbot certonly --standalone -d dbadeeds.ai
sudo cp /etc/letsencrypt/live/dbadeeds.ai/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/dbadeeds.ai/privkey.pem   nginx/ssl/

# Option B: Self-signed (testing only)
openssl req -x509 -newkey rsa:4096 -keyout nginx/ssl/privkey.pem \
  -out nginx/ssl/fullchain.pem -days 365 -nodes \
  -subj "/CN=dbadeeds.ai"
```

### 5. Launch
```bash
docker compose up -d
docker compose logs -f app   # tail logs
```

App is live at `https://your-server-ip` or `https://dbadeeds.ai`

---

## Bare Metal / VM (without Docker)

### 1. Python 3.12 setup
```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip libpq-dev gcc

cd /opt/dbadeedsai
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env && nano .env
```

### 3. Test startup
```bash
source venv/bin/activate
python wsgi.py
# Should say: Running on http://0.0.0.0:5000
```

### 4. systemd service (auto-start on boot)
```bash
sudo nano /etc/systemd/system/dbadeedsai.service
```
```ini
[Unit]
Description=dbadeeds.ai Flask Application
After=network.target redis.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/dbadeedsai
EnvironmentFile=/opt/dbadeedsai/.env
ExecStart=/opt/dbadeedsai/venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dbadeedsai
sudo systemctl status dbadeedsai
```

### 5. Nginx on bare metal
```bash
sudo apt install nginx
sudo cp nginx/nginx.conf /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl restart nginx
```

---

## API Usage Examples

### Login and get token
```bash
curl -X POST https://dbadeeds.ai/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
# → {"access_token": "eyJ...", "refresh_token": "eyJ..."}
```

### Use token in subsequent requests
```bash
TOKEN="eyJ..."

# List connections
curl -H "Authorization: Bearer $TOKEN" https://dbadeeds.ai/api/connections/

# Run a query
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM pg_stat_activity LIMIT 5", "db_type": "postgres"}' \
  https://dbadeeds.ai/api/query/execute

# AI chat
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "top 5 slowest queries last 7 days", "db_type": "postgres"}' \
  https://dbadeeds.ai/api/ai/chat
```

### Streaming AI (curl)
```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "explain pg_stat_statements", "db_type": "postgres"}' \
  --no-buffer https://dbadeeds.ai/api/ai/chat/stream
# → data: {"token": "pg_stat"}
# → data: {"token": "_statements"}
# → data: {"done": true}
```

---

## API Documentation

Interactive Swagger UI: `https://dbadeeds.ai/api/docs`

---

## Migrating from Streamlit

The Flask app **reuses all your existing backend modules unchanged**:

| Module                | Used by Flask via         |
|-----------------------|---------------------------|
| `sql_safety.py`       | `app/api/query.py`        |
| `user_management.py`  | `app/api/auth.py`, `users.py` |
| `content_filter.py`   | `app/api/ai.py`           |

You can run both Streamlit and Flask simultaneously during transition — they share the same `users.json` and `db_connections.json` files.

---

## Python Version Note

Python 3.14 is in alpha (as of early 2026) and most libraries (psycopg2, oracledb, bcrypt, LangChain) don't have stable wheels for it yet. **Python 3.12** is the current production standard — it's fast, fully supported, and all your dependencies work out of the box.

---

## Monitoring

```bash
# Check running workers
docker compose ps

# Application logs
docker compose logs -f app

# Nginx access log
docker compose exec nginx tail -f /var/log/nginx/access.log

# Redis health
docker compose exec redis redis-cli ping
```
