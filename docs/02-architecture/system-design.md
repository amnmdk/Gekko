# System Design

## Module Map

ndbot is organised into **13 packages** under `src/ndbot/`, each with a single responsibility:

```
src/ndbot/
├── config/          Configuration schema (Pydantic v2) + YAML loader
├── feeds/           News ingestion — RSS reader, synthetic generator, async manager
├── classifier/      NLP pipeline — keyword classifier, entity extractor
├── signals/         Trade decision — confidence model, confirmation engine, generators
├── market/          Market data — OHLCV feed, regime detector, synthetic candles
├── portfolio/       Position management — risk engine, portfolio engine, metrics
├── research/        Academic tools — event study, walk-forward validation
├── storage/         Persistence — SQLAlchemy ORM, database abstraction
├── execution/       Runtime — simulation engine, paper trading engine
├── geo/             Geospatial — coordinate mapping for dashboard markers
├── api/             Web API — FastAPI app, REST routes, WebSocket handler
├── metrics.py       CLI output — Rich-formatted tables
└── cli.py           Entry point — Click command group (10 commands)
```

---

## Signal Flow

The core pipeline processes news events through a linear chain of transformations:

```
                          ┌─────────────────┐
                          │   RSS Feeds      │
                          │   (async poll)   │
                          └────────┬─────────┘
                                   │ NewsEvent
                                   ▼
                          ┌─────────────────┐
                          │  Feed Manager    │
                          │  (deduplication) │
                          └────────┬─────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │     Keyword Classifier    │
                    │  + Entity Extractor       │
                    │  (domain, sentiment, NER) │
                    └────────────┬─────────────┘
                                 │ enriched NewsEvent
                                 ▼
                    ┌──────────────────────────┐
                    │    Confidence Model       │
                    │  (5-dimension Bayesian    │
                    │   posterior update)        │
                    └────────────┬─────────────┘
                                 │ confidence ∈ [0.05, 0.95]
                                 ▼
                    ┌──────────────────────────┐
                    │  Signal Generator         │
                    │  (ENERGY_GEO or           │
                    │   AI_RELEASES)            │
                    └────────────┬─────────────┘
                                 │ TradeSignal (if confidence ≥ threshold)
                                 ▼
              ┌──────────────────────────────────┐
              │     Confirmation Engine           │
              │  (breakout + volume + volatility) │
              │          ← Market Data            │
              └──────────────┬───────────────────┘
                             │ confirmed signal
                             ▼
              ┌──────────────────────────────────┐
              │        Risk Engine                │
              │  (sizing, limits, circuit         │
              │   breakers)                       │
              └──────────────┬───────────────────┘
                             │ SizingResult (if approved)
                             ▼
              ┌──────────────────────────────────┐
              │     Portfolio Engine               │
              │  (position lifecycle,              │
              │   equity tracking)                 │
              └──────────────┬───────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              ┌──────────┐    ┌──────────────┐
              │ Database  │    │   Metrics    │
              │ (SQLite)  │    │ (Sharpe etc) │
              └──────────┘    └──────────────┘
```

---

## Design Principles

### 1. Separation of Concerns
Each module does one thing. The signal generator doesn't know about risk. The risk engine doesn't know about feeds. This enables independent testing and replacement.

### 2. Sandbox-First Safety
Paper trading defaults to DRY_RUN=true with sandbox required. Two explicit settings must be changed to submit testnet orders. Live trading requires code changes.

### 3. Research-First Design
Every run produces reproducible results via fixed seeds. All data is persisted to SQLite for post-hoc analysis. Event studies and walk-forward testing are first-class citizens.

### 4. Pi-Friendly Performance
No heavy ML models. No GPU requirements. Keyword classification is O(n) per event. The full simulation runs in 3-5 seconds on a Pi 5.

### 5. Observable by Default
Every run saves metrics JSON. Rotating log files capture all decisions. The REST API + WebSocket enable real-time monitoring. Database stores full audit trail.

---

## Component Interaction Matrix

| Producer → Consumer | Config | Feeds | Classifier | Signals | Market | Portfolio | Storage |
|---|---|---|---|---|---|---|---|
| **Config** | — | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| **Feeds** | — | — | ✓ | — | — | — | ✓ |
| **Classifier** | — | — | — | ✓ | — | — | — |
| **Signals** | — | — | — | — | — | ✓ | — |
| **Market** | — | — | — | ✓ | — | ✓ | — |
| **Portfolio** | — | — | — | — | ✓ | — | ✓ |
| **Storage** | — | — | — | — | — | — | — |
