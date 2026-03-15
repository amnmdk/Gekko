# Overview

## What is ndbot?

ndbot is a **modular, event-driven systematic trading research framework** that ingests news via RSS feeds, scores events using a multi-criteria system, generates directional trade signals, and manages a full portfolio with risk controls.

It is designed to run on a **Raspberry Pi 5** and operates fully offline in simulation mode.

---

## Core Capabilities

### News Ingestion & Classification
- Polls RSS/Atom feeds asynchronously with retry/backoff
- Classifies events into domains: `ENERGY_GEO` and `AI_RELEASES`
- Extracts named entities (organisations, locations, chokepoints)
- Assigns credibility weights per source

### Multi-Criteria Confidence Scoring
The confidence model evaluates every news event on **five dimensions**:

| Dimension | What it measures | Weight |
|---|---|---|
| Source Credibility | Feed reliability (Reuters=1.8, blog=0.8) | Log-odds shift |
| Importance Score | Entity significance (chokepoints, major labs) | Log-odds shift |
| Clustering Density | How many recent events share keywords | Tanh-bounded boost |
| Corroboration Count | Distinct sources reporting same story | Tanh-bounded boost |
| Sentiment Magnitude | Strength of bullish/bearish signal | Linear boost |

Output: a single **confidence score ∈ [0.05, 0.95]** — never absolutely certain, never absolutely null.

### Signal Generation & Confirmation
- Per-domain signal generators (Energy/Geo, AI/Releases)
- Market confirmation required: breakout + volume spike + volatility expansion
- Risk-adjusted position sizing with ATR-based stop placement

### Portfolio & Risk Management
- Fixed-fractional risk model with regime-adaptive sizing
- Stop-loss, take-profit, time-stop, daily loss limit, drawdown circuit breaker
- Full equity curve tracking with Sharpe, Sortino, Calmar, profit factor

### Research Tools
- **Event Study**: Measure average price impact at multiple horizons
- **Walk-Forward Validation**: Rolling out-of-sample testing
- **Grid Search**: Parameter optimisation over confidence and risk thresholds

---

## What ndbot Does NOT Do

| Limitation | Reason |
|---|---|
| Execute real trades by default | DRY_RUN=true; sandbox required |
| Use heavy ML/LLM models | Too slow for Pi 5; rule-based is faster and auditable |
| Guarantee profitability | Research tool — past performance ≠ future returns |
| Provide financial advice | For educational and research purposes only |
| Handle options/futures | Crypto spot via CCXT; extension possible |

---

## Execution Modes

| Mode | Data Source | API Required | Use Case |
|---|---|---|---|
| `simulate` | Synthetic events + candles | No | Strategy development |
| `backtest` | Stored JSON/CSV files | No | Historical replay |
| `paper` | Live RSS + exchange testnet | Yes (CCXT) | Pre-production validation |

---

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Config | Pydantic v2, YAML |
| CLI | Click + Rich |
| HTTP | aiohttp, feedparser |
| Market Data | CCXT (100+ exchanges) |
| Database | SQLite via SQLAlchemy |
| API | FastAPI + WebSocket |
| Frontend | Leaflet.js dashboard |
| Deployment | Docker (ARM64), systemd |
| CI/CD | GitHub Actions |
| Testing | pytest (87 tests) |
| Linting | ruff, black, mypy |
