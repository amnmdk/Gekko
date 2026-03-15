# Changelog

## v0.2.0 — 2026-03-14 — Beta

### Major: Upgrade project from alpha to beta research framework

**New Features**:
- `ndbot export` — Export trades/events from any run to CSV or JSON
- `ndbot validate-config` — Health-check table for config values with optional feed URL reachability
- Rotating log file — All runs write to `logs/ndbot.log` (10 MB × 3 backups)
- Per-run metrics JSON — Automatic `results/run_{id}_metrics.json` after simulate/paper
- RSS retry/backoff — Up to 3 attempts with 2s/4s/8s exponential backoff on 429 and timeouts
- GitHub Actions CI — ruff lint + mypy + pytest (87 tests + coverage) + CLI smoke + Docker ARM64 build
- FastAPI dashboard API — REST endpoints and WebSocket for live trading state
- Docker multi-stage — Separate `Dockerfile.backend` (FastAPI/uvicorn) and `Dockerfile.frontend` (nginx)
- Full pytest test suite — 87 tests covering API, signals, data integrity, determinism

**Bug Fixes**:
- Backtest command now correctly injects external candles and events into SimulationEngine
- `SimulationEngine` properly uses `external_candles` / `external_events` (no more silent override)

**Quality**:
- All public functions type-annotated
- Pydantic v2 strict field validation on all config values
- 0 ruff errors, 0 black formatting issues
- Version bumped to 0.2.0

---

## v0.1.0 — 2026-03-03 — Alpha

### Initial production-grade framework

**Core Pipeline**:
- Async RSS feed reader + synthetic event generator
- Keyword classifier + entity extractor (no transformers)
- Bayesian confidence model (5-dimension scoring)
- Confirmation engine (breakout + volume + volatility)
- ENERGY_GEO and AI_RELEASES signal generators
- GBM+GARCH synthetic candle generator
- ATR/MA-based regime detection
- CCXT live market data integration
- Fixed-fractional risk engine with regime-adaptive sizing
- Full position lifecycle (SL, TP, time-stop, daily loss, drawdown)
- Sharpe, Sortino, Calmar, profit factor, expectancy metrics
- Event study analysis with t-statistics and vol expansion
- Rolling walk-forward validation
- SQLite persistence (events, trades, runs, walkforward, grid)
- Simulation engine (zero external dependencies)
- Paper trading engine (CCXT testnet, DRY_RUN safe)
- 8 CLI commands (simulate, backtest, event-study, walkforward, grid, paper, status, seed-demo)
- ARM64 Dockerfile + docker-compose profiles
- 17 initial tests

---

## Planned

### v0.3.0 — Research Enhancements
- [ ] Multi-criteria AI news scoring (optional Claude/GPT integration)
- [ ] Trading "plans" — target + timeframe + strategy config
- [ ] Multi-symbol support
- [ ] Multi-market support (crypto, stocks, forex)
- [ ] Volatility criteria / volume threshold filtering
- [ ] Analytics dashboard with per-plan reporting

### v0.4.0 — Operational
- [ ] Prometheus metrics endpoint
- [ ] Slack / Telegram alerts on drawdown breach
- [ ] Rich TUI live dashboard (terminal)
- [ ] Automatic data retention cleanup

### v0.5.0 — Multi-Strategy
- [ ] Plugin architecture for custom signal generators
- [ ] Multi-exchange routing abstraction
- [ ] Strategy registry with hot-reload
