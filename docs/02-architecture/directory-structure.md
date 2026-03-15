# Directory Structure

```
ndbot/
├── .github/
│   └── workflows/
│       └── ci.yml                    GitHub Actions: lint + test + Docker build
│
├── config/
│   └── sample.yaml                   Full configuration template with comments
│
├── data/                             Runtime databases (gitignored)
│   ├── .gitkeep
│   ├── ndbot.db                      Main SQLite database
│   └── demo_*.db                     Seed-demo databases
│
├── docs/                             This documentation (Notion/Obsidian-ready)
│   ├── index.md                      Navigation hub
│   ├── 01-getting-started/           Installation, quickstart, CLI
│   ├── 02-architecture/              System design, data flow
│   ├── 03-modules/                   Per-module deep dives
│   ├── 04-configuration/             Config reference, examples
│   ├── 05-research/                  Event study, walk-forward, grid
│   ├── 06-operations/                Deployment, Docker, CI/CD
│   ├── 07-api-dashboard/             REST API, WebSocket, frontend
│   ├── 08-risk-safety/               Risk management, safety guards
│   ├── 09-development/               Contributing, test suite, changelog
│   └── 10-troubleshooting/           FAQ, errors, performance
│
├── frontend/
│   ├── index.html                    Leaflet.js map + dashboard
│   ├── js/main.js                    WebSocket + API client (~600 lines)
│   └── css/style.css                 Dark theme styling (~500 lines)
│
├── logs/                             Rotating log files (gitignored)
│   └── ndbot.log                     Main log (10MB × 3 backups)
│
├── results/                          Charts, reports, metrics JSON (gitignored)
│   ├── .gitkeep
│   ├── run_*_metrics.json            Per-run performance metrics
│   └── event_study_*.png             Event study charts
│
├── src/ndbot/
│   ├── __init__.py                   Package version (0.2.0)
│   ├── cli.py                        Click CLI — 10 commands, logging setup
│   ├── metrics.py                    Rich table formatters for CLI output
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py               Pydantic v2 config schema (9 model classes)
│   │   └── loader.py                 YAML config loader
│   │
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── base.py                   NewsEvent dataclass, EventDomain enum, BaseFeed ABC
│   │   ├── rss_feed.py               Async RSS reader with retry/backoff
│   │   ├── synthetic.py              Deterministic synthetic event generator
│   │   └── manager.py                FeedManager — async polling coordinator
│   │
│   ├── classifier/
│   │   ├── __init__.py
│   │   ├── keyword_classifier.py     Domain classification, sentiment, keywords
│   │   └── entity_extractor.py       Pattern-based NER (ORG, LOCATION, CHOKEPOINT)
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── base.py                   TradeSignal dataclass, SignalDirection enum
│   │   ├── confidence_model.py       5-dimension Bayesian confidence scorer
│   │   ├── confirmation.py           Market confirmation engine (breakout/vol/ATR)
│   │   ├── energy_geo.py             EnergyGeoSignalGenerator
│   │   └── ai_releases.py            AIReleasesSignalGenerator
│   │
│   ├── market/
│   │   ├── __init__.py
│   │   ├── data.py                   MarketDataFeed wrapper (CCXT + synthetic)
│   │   ├── regime.py                 RegimeDetector — volatility + trend regimes
│   │   └── synthetic_candles.py      GBM+GARCH synthetic candle generator
│   │
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── position.py               Position dataclass, PositionStatus, CloseReason
│   │   ├── engine.py                 PortfolioEngine — position lifecycle
│   │   ├── risk.py                   RiskEngine — sizing and pre-trade checks
│   │   └── metrics.py                PerformanceReport, Sharpe/Sortino/Calmar
│   │
│   ├── research/
│   │   ├── __init__.py
│   │   ├── event_study.py            Event study at multiple horizons
│   │   └── walkforward.py            Walk-forward OOS validation + grid search
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── simulate.py               SimulationEngine — offline pipeline
│   │   └── paper.py                  PaperEngine — CCXT exchange integration
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── models.py                 SQLAlchemy ORM (5 tables)
│   │   └── database.py               Database abstraction layer
│   │
│   ├── geo/
│   │   ├── __init__.py
│   │   └── coordinates.py            Lat/lon mapping for dashboard markers
│   │
│   └── api/
│       ├── __init__.py
│       ├── app.py                    FastAPI app + lifespan + logging
│       ├── engine.py                 APIEngine — state machine
│       ├── state.py                  AppState — synchronised trading state
│       ├── routes.py                 13 REST endpoints
│       └── ws.py                     WebSocket handler
│
├── tests/
│   ├── __init__.py
│   ├── test_basic.py                 21 tests — core pipeline + smoke tests
│   ├── test_api.py                   26 tests — REST + WebSocket integration
│   ├── test_signals.py               17 tests — signal gen, confidence, NER
│   └── test_validation.py            22 tests — data integrity, determinism
│
├── Dockerfile                        Main CLI image (python:3.11-slim)
├── Dockerfile.backend                FastAPI backend image
├── Dockerfile.frontend               Nginx frontend image
├── docker-compose.yml                Multi-service orchestration
├── nginx.conf                        Reverse proxy configuration
├── pyproject.toml                    Project metadata + tool config
├── requirements.txt                  Runtime dependencies
├── .gitignore                        Standard Python + data exclusions
├── .dockerignore                     Docker build exclusions
└── README.md                         Project readme
```

---

## Database Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `events` | All ingested news events | event_id, run_id, domain, headline, sentiment_score |
| `trades` | All opened/closed positions | position_id, run_id, direction, entry/exit price, PnL |
| `runs` | Run metadata and summary | run_id, mode, initial_capital, sharpe, max_drawdown |
| `walkforward_results` | Walk-forward OOS windows | window_idx, best_params, oos_sharpe |
| `grid_results` | Grid search parameter sweeps | min_confidence, risk_per_trade, sharpe |
