# Docker Guide

## Images

ndbot provides three Dockerfiles:

| File | Image | Purpose | Base |
|---|---|---|---|
| `Dockerfile` | `ndbot:latest` | CLI commands | `python:3.11-slim` |
| `Dockerfile.backend` | `ndbot-backend` | FastAPI API server | `python:3.11-slim` |
| `Dockerfile.frontend` | `ndbot-frontend` | Nginx dashboard | `nginx:latest` |

---

## Building

### Standard Build

```bash
docker compose build
```

### ARM64 Build (Pi 5)

```bash
# Native on Pi 5 (no emulation needed)
docker build -t ndbot:latest .

# Cross-compile from x86 for ARM64
docker buildx build --platform linux/arm64 -t ndbot:latest .
```

---

## Docker Compose Services

```yaml
services:
  backend:       # FastAPI + uvicorn (port 8000)
  frontend:      # Nginx dashboard (port 80, depends on backend)
  cli:           # One-off CLI commands
  simulate:      # Research profile
  walkforward:   # Research profile
```

### Start Dashboard

```bash
docker compose up -d backend frontend
# Open http://localhost
```

### Run CLI Commands

```bash
# Simulation
docker compose run --rm cli simulate -c config/sample.yaml

# Demo
docker compose run --rm cli seed-demo

# Status
docker compose run --rm cli status

# Export
docker compose run --rm cli export --run-id <id> --format csv
```

### Research Commands

```bash
# Start research profile
docker compose --profile research up simulate
docker compose --profile research up walkforward
```

---

## Volumes

| Volume | Mount Point | Purpose |
|---|---|---|
| `ndbot-data` | `/app/data/` | SQLite databases |
| `ndbot-results` | `/app/results/` | Charts, metrics JSON |
| `ndbot-logs` | `/app/logs/` | Rotating log files |

Data persists across container restarts.

### Backup

```bash
# Backup database
docker compose run --rm cli sh -c "cp /app/data/ndbot.db /app/results/backup_$(date +%Y%m%d).db"

# Or from host
docker cp ndbot-backend:/app/data/ndbot.db ./backup.db
```

---

## Health Checks

### Backend

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 15s
```

### Frontend

Depends on backend being healthy before starting.

---

## Environment Variables

```yaml
services:
  backend:
    environment:
      - NDBOT__PAPER__API_KEY=${PAPER_API_KEY}
      - NDBOT__PAPER__API_SECRET=${PAPER_API_SECRET}
      - NDBOT__LOG_LEVEL=INFO
```

Use a `.env` file:

```bash
# .env (gitignored)
PAPER_API_KEY=your_testnet_key
PAPER_API_SECRET=your_testnet_secret
```

---

## Nginx Configuration

The frontend container runs nginx with reverse proxy:

- `/` → static files (index.html, js/, css/)
- `/api/*` → proxy to `backend:8000/api/*`
- `/ws` → WebSocket proxy to `backend:8000/ws`

---

## Troubleshooting Docker

| Issue | Solution |
|---|---|
| Backend unhealthy | Check `docker compose logs backend` |
| Frontend 502 | Backend not ready yet; wait for health check |
| Permission denied on volumes | Run `chmod 777 data/ logs/ results/` on host |
| ARM64 build fails | Use `docker buildx create --use` first |
| High memory usage | Reduce `candle_window` in config |
