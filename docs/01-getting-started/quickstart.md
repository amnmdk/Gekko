# Quickstart — First Run in 5 Minutes

## Step 1: Run the Demo

No configuration file needed. This generates synthetic data and runs the full pipeline:

```bash
ndbot seed-demo
```

**What happens**:
1. Creates a minimal config in memory
2. Generates 30 synthetic news events per domain (ENERGY_GEO + AI_RELEASES)
3. Generates 600 synthetic OHLCV candles (BTC/USDT, 5-minute)
4. Runs the full pipeline: classify → score → signal → confirm → trade → report
5. Runs an event study analysis
6. Saves results to `results/` and database to `data/`

**Output**: A Rich-formatted performance table showing trades, PnL, Sharpe ratio, and more.

---

## Step 2: Run a Simulation with Config

```bash
ndbot simulate --config config/sample.yaml --seed 42
```

This uses the sample configuration which defines:
- BTC/USDT market on 5-minute candles
- RSS feeds for Reuters Commodities, TechCrunch AI, OpenAI Blog, Anthropic News
- Both signal domains enabled (ENERGY_GEO + AI_RELEASES)
- $100 initial capital, 1% risk per trade, 2:1 reward-risk ratio
- 15% drawdown circuit breaker, 5% daily loss limit

---

## Step 3: Check Your Results

```bash
# View recent runs
ndbot status

# Export trades to CSV
ndbot export --run-id <run-id-from-status> --what trades --format csv
```

---

## Step 4: Validate Your Config

```bash
# Health-check your configuration
ndbot validate-config --config config/sample.yaml

# Also check if feed URLs are reachable
ndbot validate-config --config config/sample.yaml --check-feeds
```

---

## Step 5: Explore Research Tools

```bash
# Event study — measure price impact of news events
ndbot event-study --config config/sample.yaml --n-events 30

# Walk-forward validation — out-of-sample parameter testing
ndbot walkforward --config config/sample.yaml --n-events 200

# Grid search — find optimal confidence/risk parameters
ndbot grid --config config/sample.yaml --n-events 100
```

---

## Step 6: Launch the Dashboard

```bash
# Using Docker Compose
docker compose up -d

# Open in browser
# http://localhost:80
```

The dashboard shows:
- Live map with event markers (ENERGY_GEO = red, AI_RELEASES = purple)
- Real-time equity curve chart
- Open positions and trade history table
- Settings modal for runtime parameter tweaks

---

## Next Steps

- [[../04-configuration/config-reference|Configuration Reference]] — Customise every parameter
- [[../05-research/interpreting-results|Interpreting Results]] — What the numbers mean
- [[../08-risk-safety/paper-trading|Paper Trading Safety]] — Safe testnet setup
