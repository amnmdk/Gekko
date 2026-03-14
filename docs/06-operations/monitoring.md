# Monitoring & Logging

## Logging System

ndbot uses Python's standard `logging` module with two handlers:

### Console Handler

- Output: `stdout`
- Level: Configurable via `--log-level` (default: INFO)
- Format: `HH:MM:SS [LEVEL] module: message`

### File Handler

- Output: `logs/ndbot.log`
- Level: Always DEBUG (captures everything regardless of console level)
- Rotation: 10 MB × 3 backups (auto-rotated)
- Encoding: UTF-8

### Log Levels

| Level | Use |
|---|---|
| `DEBUG` | All decisions, scores, sizing details |
| `INFO` | Position opens/closes, run start/end |
| `WARNING` | Feed errors, rejected signals, rate limits |
| `ERROR` | Unrecoverable failures |

### Silenced Loggers

These third-party loggers are suppressed to WARNING level:
- `urllib3`
- `ccxt`
- `aiohttp`
- `feedparser`

---

## Health Monitoring

### CLI Status Check

```bash
ndbot status
```

Shows table of recent runs with PnL, Sharpe, trade count.

### REST API Health Endpoint

```bash
curl http://localhost:8000/api/health
# {"status": "ok", "running": true, "balance": 100.00}
```

### Docker Health Check

Built into `docker-compose.yml`:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

---

## Key Log Messages

### Normal Operation

```
INFO  SimulationEngine: === SIMULATION START: abc123 ===
INFO  SimulationEngine: Loaded 80 events (synthetic)
INFO  SimulationEngine: Using external candles (500 rows)
INFO  PortfolioEngine: POSITION OPENED: abc SHORT BTC/USDT @ 45000.00
INFO  PortfolioEngine: POSITION CLOSED: abc SHORT | PnL=0.5432 | reason=TAKE_PROFIT
INFO  SimulationEngine: === SIMULATION COMPLETE: 15 trades | equity=102.34 ===
```

### Warning Signs

```
WARNING RSSFeed: Feed reuters-commodities rate-limited (HTTP 429), retry 1/3 in 2s
WARNING PortfolioEngine: Signal abc rejected by confirmation: breakout_not_met
WARNING RiskEngine: Signal rejected: max_concurrent_positions_reached (3)
```

### Errors

```
ERROR  RSSFeed: Feed reuters-commodities failed after 3 attempts: ConnectionError
ERROR  PaperEngine: SAFETY BLOCK: Cannot run paper mode with dry_run=false and sandbox=false
```

---

## Monitoring in Paper Mode

### Real-time WebSocket

Connect to `ws://localhost:8000/ws` for live updates:

```json
{"type": "snapshot", "data": {
  "summary": {"balance": 100.00, "total_pnl": 2.34},
  "events": [...],
  "positions": [...],
  "trades": [...],
  "equity_curve": [...],
  "prices": {"BTC/USDT": 45000.00}
}}
```

### Dashboard

Open `http://localhost:80` for the live Leaflet.js dashboard with:
- Equity curve chart
- Open positions table
- Trade history with PnL
- Event feed with map markers
- Settings modal for runtime tweaks

---

## Per-Run Metrics

Every simulation/backtest automatically saves:

```
results/run_{run_id}_metrics.json
```

Contains the full performance summary:
- Equity, return %, PnL
- Sharpe, Sortino, Calmar
- Win rate, profit factor
- Max drawdown
- Trade count

---

## Database Inspection

For deep analysis, query SQLite directly:

```bash
sqlite3 data/ndbot.db

-- Recent runs
SELECT run_id, run_name, mode, total_trades, total_pnl, sharpe_ratio
FROM runs ORDER BY start_time DESC LIMIT 10;

-- Trades for a specific run
SELECT position_id, direction, entry_price, exit_price, realised_pnl, close_reason
FROM trades WHERE run_id = 'abc123';

-- Events by domain
SELECT COUNT(*), domain FROM events GROUP BY domain;
```
