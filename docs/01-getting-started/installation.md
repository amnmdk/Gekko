# Installation

## Requirements

- **Python 3.11+** (3.12 and 3.13 also supported)
- **pip** (package manager)
- **Git** (for cloning the repository)
- ~500MB RAM (simulate mode), ~1GB (paper mode)

---

## Native Installation

### 1. Clone the Repository

```bash
git clone https://github.com/amnmdk/Gekko.git
cd Gekko
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# OR
.venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -e .
```

### 4. Install Dev Dependencies (optional)

```bash
pip install -e ".[dev]"
```

This adds: pytest, pytest-asyncio, pytest-cov, httpx, black, ruff, mypy, types-PyYAML, types-tabulate

### 5. Verify Installation

```bash
ndbot --version
# ndbot, version 0.2.0

ndbot seed-demo
# Should produce performance report + event study chart
```

---

## Docker Installation

### Prerequisites
- Docker Engine 20.10+
- Docker Compose v2

### Build Images

```bash
# Build all images (CLI + backend + frontend)
docker compose build

# Build for ARM64 specifically (Pi 5)
docker buildx build --platform linux/arm64 -t ndbot:latest -f Dockerfile .
```

### Run with Docker Compose

```bash
# Run the full dashboard (backend + frontend)
docker compose up -d

# Run a simulation
docker compose run --rm cli simulate --config config/sample.yaml

# Run the demo
docker compose run --rm cli seed-demo
```

### Available Services

| Service | Port | Description |
|---|---|---|
| `backend` | 8000 | FastAPI + WebSocket |
| `frontend` | 80 | Nginx dashboard |
| `cli` | — | One-off CLI commands |
| `simulate` | — | Research profile |
| `walkforward` | — | Research profile |

---

## Raspberry Pi 5 Installation

### System Setup

```bash
# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Python 3.11+ and build tools
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
  git gcc g++ libffi-dev libssl-dev

# Optional: install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

### Native Install on Pi

```bash
git clone https://github.com/amnmdk/Gekko.git
cd Gekko
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
ndbot seed-demo
```

### Docker on Pi (ARM64 Native)

```bash
# Build natively on ARM64 — no emulation needed
docker build -t ndbot:latest .
docker compose up -d
```

### Performance Expectations

| Operation | Time on Pi 5 |
|---|---|
| `seed-demo` | ~3-5 seconds |
| `simulate` (40 events, 500 candles) | ~3-5 seconds |
| `walkforward` (50k candles, 200 events) | ~60-120 seconds |
| `paper` mode idle CPU | <5% at 5m intervals |

> **Tip**: Avoid running `walkforward` with >50k candles in a single pass. Use `--n-events` to limit.

---

## Verifying the Installation

Run the full test suite:

```bash
pytest tests/ -v
```

Expected output: **87 passed** in ~4 seconds.

Run lint checks:

```bash
ruff check src/ tests/
black --check src/ tests/
```

Expected: **All checks passed** / **All done!**
