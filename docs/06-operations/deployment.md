# Deployment Guide

## Deployment Options

| Method | Best For | Complexity |
|---|---|---|
| Native Python | Development, Pi 5 | Low |
| Docker Compose | Production, multi-service | Medium |
| Systemd Service | Headless Pi 5 paper trading | Low |

---

## Native Deployment

### Production Setup on Pi 5

```bash
# 1. Install
git clone https://github.com/amnmdk/Gekko.git /opt/ndbot
cd /opt/ndbot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Create config
cp config/sample.yaml config/production.yaml
# Edit config/production.yaml with your settings

# 3. Validate
ndbot validate-config -c config/production.yaml --check-feeds

# 4. Test simulation
ndbot simulate -c config/production.yaml --seed 42

# 5. Start paper trading (foreground)
ndbot paper -c config/production.yaml --duration 3600
```

---

## Systemd Service (Pi 5)

For headless, always-on paper trading:

### Create Service File

```ini
# /etc/systemd/system/ndbot-paper.service
[Unit]
Description=ndbot Paper Trading
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/opt/ndbot
ExecStart=/opt/ndbot/.venv/bin/ndbot paper --config config/production.yaml
Restart=on-failure
RestartSec=30s
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/opt/ndbot/data /opt/ndbot/logs /opt/ndbot/results

# Environment
Environment=NDBOT__PAPER__DRY_RUN=true
EnvironmentFile=-/opt/ndbot/.env

[Install]
WantedBy=multi-user.target
```

### Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable ndbot-paper
sudo systemctl start ndbot-paper

# View logs
sudo journalctl -u ndbot-paper -f

# Check status
sudo systemctl status ndbot-paper
```

### Auto-restart on Failure

The service restarts after 30 seconds on any failure. This handles:
- Network outages (RSS fetch failures)
- Exchange API timeouts
- Python exceptions

---

## Docker Compose Deployment

See [[docker|Docker Guide]] for full Docker documentation.

### Quick Start

```bash
cd /opt/ndbot
docker compose up -d

# Check status
docker compose ps
docker compose logs -f backend
```

### Services

| Service | Exposed | Description |
|---|---|---|
| `backend` | :8000 | FastAPI + trading engine |
| `frontend` | :80 | Nginx dashboard |

---

## Production Checklist

- [ ] Config validated with `ndbot validate-config --check-feeds`
- [ ] Feed URLs are reachable from deployment host
- [ ] Logs directory exists and is writable
- [ ] Database directory exists and is writable
- [ ] DRY_RUN=true for initial deployment
- [ ] API keys set via environment variables (not in config)
- [ ] Systemd service tested with `--duration 60` first
- [ ] Log rotation configured (built-in: 10MB × 3 files)
- [ ] Monitoring: check `ndbot status` output periodically
