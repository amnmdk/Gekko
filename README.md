# ndbot — News-Driven Intraday Trading Research Framework

> A production-grade, event-driven systematic trading research framework
> designed for Raspberry Pi 5 deployment and academic rigour.

---

## What This System Does

ndbot is a modular, research-first event-driven trading framework that:

- **Ingests** news events from RSS/Atom feeds across two domains:
  - `ENERGY_GEO` — Africa/Middle East geopolitics, chokepoints (Hormuz, Suez, Bab el-Mandeb), sanctions, refinery/pipeline attacks
  - `AI_RELEASES` — OpenAI, Anthropic, major AI lab product announcements, security incidents, infrastructure tools
- **Classifies** events using lightweight keyword + entity matching (no heavy transformer models)
- **Scores** confidence via a Bayesian-style posterior update over source credibility, clustering density, corroboration, and entity importance
- **Generates** directional trade signals per domain based on sentiment and keyword polarity
- **Confirms** signals against market conditions (breakout, volume spike, volatility expansion)
- **Manages** a full portfolio with risk-based sizing, stop-loss, time-stop, daily loss limit, and drawdown circuit breaker
- **Tracks** equity curve, Sharpe ratio, Sortino, profit factor, expectancy, and max drawdown
- **Persists** all events, trades, and run metadata to SQLite
- **Analyses** historical event impact through a rigorous event study
- **Validates** strategy parameters out-of-sample via rolling walk-forward testing
- **Runs fully offline** in `simulate` mode with synthetic data — no external APIs required

## What This System Does NOT Do

| What it does NOT do | Why |
|---|---|
| Execute real trades | Designed for research; paper mode uses testnet only |
| Use transformer/LLM models | Too heavy for Pi 5; rule-based is faster and more auditable |
| Make investment recommendations | This is a research tool, not financial advice |
| Guarantee profitability | No backtested strategy guarantees future returns |
| Access private data | Only public RSS feeds; no scrapers or private APIs |
| Handle equities, futures, or options | Designed for crypto spot; extension possible |
| Provide statistical significance | Small sample event studies are exploratory only |

---

## Architecture Overview

```
src/ndbot/
├── config/          ← Pydantic config schema + YAML loader
├── feeds/           ← RSS feed reader, synthetic generator, feed manager
├── classifier/      ← Keyword classifier, entity extractor
├── signals/         ← Confidence model, confirmation engine, per-domain generators
├── market/          ← OHLCV data feed, regime detector, synthetic candles
├── portfolio/       ← Position, risk engine, portfolio engine, metrics
├── research/        ← Event study, walk-forward validation
├── storage/         ← SQLAlchemy models, database abstraction
├── execution/       ← Simulation engine, paper trading engine
├── metrics.py       ← Rich-formatted CLI output helpers
└── cli.py           ← Click CLI entry point
```

### Signal Flow

```
RSS Feed → FeedManager → Classifier → Confidence Model
                                           ↓
                                    Signal Generator
                                           ↓
                                  Confirmation Engine  ← Market Data
                                           ↓
                                   Portfolio Engine    ← Risk Engine
                                           ↓
                                      Position Open/Close
                                           ↓
                                       Database + Metrics
```

---

## Execution Modes

### `simulate` — Research mode (no real money, no APIs)

Uses synthetic events and candles. The full risk engine, portfolio, and research pipeline run normally. Designed for strategy development and parameter exploration.

```bash
ndbot simulate --config config/sample.yaml
```

### `backtest` — Historical replay

Replays stored events and candles. Load event JSON and candle CSV from disk:

```bash
ndbot backtest --config config/sample.yaml \
  --events-file data/events.json \
  --candles-file data/BTCUSDT_5m.csv
```

If no files are provided, falls back to synthetic data.

### `paper` — Paper trading on exchange testnet

Connects to a CCXT-compatible exchange sandbox. **DRY_RUN is True by default.** Sandbox is required by default.

```bash
ndbot paper --config config/sample.yaml
```

**IMPORTANT**: To submit testnet orders, set in your config:
```yaml
paper:
  exchange_id: "binance"
  dry_run: false
  require_sandbox: true
  api_key: null    # Set via NDBOT__PAPER__API_KEY env var
  api_secret: null
```

---

## CLI Reference

```bash
ndbot simulate     --config config/sample.yaml [--events 40] [--candles 500] [--seed 42]
ndbot backtest     --config config/sample.yaml [--events-file f.json] [--candles-file f.csv]
ndbot event-study  --config config/sample.yaml [--output-dir results] [--n-events 30]
ndbot walkforward  --config config/sample.yaml [--output-dir results] [--n-events 200]
ndbot grid         --config config/sample.yaml [--n-events 100]
ndbot paper        --config config/sample.yaml [--duration 3600]
ndbot status       [--db data/ndbot.db]
ndbot seed-demo    # No config required — zero-dependency demo
```

---

## Scientific Validation Methodology

### Event Study

**Purpose**: Measure the average price impact of news events at multiple horizons.

**Methodology**:
1. For each event E_i at time t_i, align a window of candles: [t_i - 12, t_i + 48] (configurable)
2. Compute normalised returns at horizons: 5m, 15m, 1h, 4h
3. Compute volatility expansion ratio: σ_post / σ_pre
4. Aggregate over all events: mean, t-statistic, % positive

**Limitations** (read carefully):
- Selection bias: we only observe events we ingested; missed events create survivor bias
- Look-ahead bias: using keyword classification with words that appear in the headline creates label leakage
- Small samples: with <50 events per category, t-statistics are unreliable
- Confounding: other events may occur within the post-event window
- Transaction costs: the naive event study does not account for slippage or spread

**Interpretation**: A t-statistic > 2.0 on the 5m return with n > 30 is suggestive. Treat as a hypothesis to test further, not a trading rule.

### Walk-Forward Validation

**Purpose**: Simulate out-of-sample performance to detect overfitting.

**Methodology**:
1. Split history into rolling windows: 3-year train / 1-year test
2. On each TRAIN window: grid search over `min_confidence` and `risk_per_trade`
3. Select best parameters by in-sample Sharpe ratio
4. Apply to TEST window; record OOS Sharpe, return, max drawdown
5. Repeat with 90-day step

**Limitations**:
- Parameter optimisation on train data still overfits if grid is large
- OOS Sharpe > 0.5 across 3+ windows is meaningful; less is noise
- Statistical significance requires >30 OOS trades per window
- Walk-forward assumes stationarity of signal quality — not guaranteed

**Rejection criteria**: If mean OOS Sharpe < 0 or >50% of windows are unprofitable, the strategy is not viable at current parameters.

---

## Raspberry Pi 5 Deployment

### Requirements

- Raspberry Pi 5 (4GB or 8GB recommended)
- Raspberry Pi OS (64-bit)
- Python 3.11+
- ~500MB RAM in simulate mode, ~1GB in paper mode

### Install (Native)

```bash
# Install system dependencies
sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv git

# Clone repository
git clone https://github.com/yourname/newsdriven-trading-bot.git
cd newsdriven-trading-bot

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -e .

# Run demo
ndbot seed-demo
```

### Install (Docker / ARM64)

```bash
# Build for ARM64 (native on Pi 5)
docker build -t ndbot:latest .

# Run demo
docker compose --profile demo up seed-demo

# Run simulation
docker compose --profile simulate up simulate
```

### Pi 5 Performance Notes

- `simulate` with 40 events + 500 candles: ~3-5 seconds
- `walkforward` with 50k candles + 200 events: ~60-120 seconds
- `paper` mode CPU usage: <5% average at 5m candle intervals
- Do not run `walkforward` with >50k candles in a single pass — use the `--n-events` limit
- matplotlib plots will work but rendering is slow; use `--log-level WARNING` to reduce I/O

### Systemd Service (Paper Mode)

```ini
# /etc/systemd/system/ndbot-paper.service
[Unit]
Description=ndbot Paper Trading
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/newsdriven-trading-bot
ExecStart=/home/pi/newsdriven-trading-bot/.venv/bin/ndbot paper --config config/sample.yaml
Restart=on-failure
RestartSec=30s
Environment=NDBOT__PAPER__DRY_RUN=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable ndbot-paper
sudo systemctl start ndbot-paper
sudo journalctl -u ndbot-paper -f
```

---

## How to Add RSS Feeds

Edit `config/sample.yaml` and add a new entry under `feeds`:

```yaml
feeds:
  - name: "my-new-feed"
    url: "https://example.com/rss.xml"
    domain: ENERGY_GEO          # or AI_RELEASES
    poll_interval_seconds: 120
    credibility_weight: 1.2      # 0.0 to 2.0
    enabled: true
```

**Credibility weight guidelines**:
- `2.0` — Primary source (Reuters, official lab blog)
- `1.5` — Tier-1 financial media (FT, Bloomberg)
- `1.2` — Specialist industry media
- `1.0` — General tech/news aggregator
- `0.8` — Unverified or low-credibility source

**Domain assignment**: The keyword classifier will further validate the domain at classification time. An incorrectly labelled feed will produce low-confidence signals that are filtered out.

---

## How to Enable Paper Trading Safely

1. **Start with DRY_RUN=true** (default). This logs all orders without submitting them.

2. **Configure a sandbox exchange** (Binance testnet is recommended):
   - Create a testnet account at https://testnet.binance.vision/
   - Generate testnet API keys

3. **Set credentials via environment variables** (never hardcode):
   ```bash
   export NDBOT__PAPER__API_KEY=your_testnet_key
   export NDBOT__PAPER__API_SECRET=your_testnet_secret
   ```

4. **Enable testnet order submission** in config:
   ```yaml
   paper:
     dry_run: false
     require_sandbox: true
   ```

5. **Verify sandbox connectivity** before running:
   ```bash
   ndbot paper --config config/sample.yaml --duration 60
   ```
   Check logs for `Exchange sandbox mode enabled.`

6. **Safety guarantees built into ndbot**:
   - If `require_sandbox=true` and exchange has no sandbox → execution is REFUSED
   - If both `dry_run=false` AND `require_sandbox=false` → `RuntimeError` is raised
   - All orders are logged with full audit trail regardless of DRY_RUN state

---

## Configuration Reference

See `config/sample.yaml` for a fully documented example.

Key parameters:

| Parameter | Default | Description |
|---|---|---|
| `portfolio.initial_capital` | `100.0` | Starting equity (USD, fictional in simulate) |
| `portfolio.max_daily_loss_pct` | `0.05` | Daily loss stops trading |
| `portfolio.max_drawdown_pct` | `0.15` | Drawdown circuit breaker |
| `portfolio.time_stop_minutes` | `240` | Force close after N minutes |
| `signals.min_confidence` | `0.45` | Minimum confidence to emit signal |
| `signals.rr_ratio` | `2.0` | Risk:reward ratio for TP placement |
| `confirmation.enabled` | `true` | Require market confirmation before entry |
| `confirmation.breakout_threshold` | `0.002` | 0.2% breakout above recent high |
| `research.train_days` | `1095` | Walk-forward training window (3 years) |
| `research.test_days` | `365` | Walk-forward test window (1 year) |

---

## Risk Warnings

**READ BEFORE USE**

1. **This is a research tool, not a trading system.** No warranty of profitability is expressed or implied.

2. **Past synthetic performance does not predict real performance.** Synthetic event studies are mathematical exercises, not predictive models.

3. **News-driven strategies are subject to extreme slippage.** By the time an RSS feed publishes an event, market prices have typically already moved. This framework does not model execution latency.

4. **Crypto markets are highly manipulated and illiquid.** The ENERGY_GEO → crypto correlation hypothesis is unproven.

5. **Keyword classifiers have high false-positive rates.** Many events that match keywords will have zero market impact. Confidence scoring mitigates but does not eliminate this.

6. **You are solely responsible for any use of this code in production.** The authors accept no liability for financial losses arising from use of this software.

7. **Paper mode uses testnet credentials.** Switching to live credentials requires explicit code changes. Even so: never trade real money without extensive independent validation.

8. **Walk-forward results with <30 OOS trades per window are statistically meaningless.**

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Type check
mypy src/ndbot/

# Format
black src/ tests/

# Lint
ruff check src/ tests/
```

---

## Project Structure

```
newsdriven-trading-bot/
├── src/ndbot/
│   ├── config/          settings.py, loader.py
│   ├── feeds/           base.py, rss_feed.py, synthetic.py, manager.py
│   ├── classifier/      keyword_classifier.py, entity_extractor.py
│   ├── signals/         base.py, confidence_model.py, confirmation.py,
│   │                    energy_geo.py, ai_releases.py
│   ├── market/          data.py, regime.py, synthetic_candles.py
│   ├── portfolio/       engine.py, position.py, risk.py, metrics.py
│   ├── research/        event_study.py, walkforward.py
│   ├── storage/         database.py, models.py
│   ├── execution/       simulate.py, paper.py
│   ├── metrics.py
│   └── cli.py
├── config/
│   └── sample.yaml
├── data/                (gitignored, created at runtime)
├── results/             (gitignored, charts and reports saved here)
├── tests/
│   └── test_basic.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## License

MIT License — see LICENSE file.

This software is provided as-is for research and educational purposes.
