# Frequently Asked Questions

## General

### What is ndbot?

A modular, event-driven systematic trading research framework. It ingests news from RSS feeds, classifies events, scores confidence, generates trade signals, and manages a portfolio with risk controls. Designed for Raspberry Pi 5.

### Can I trade real money with this?

Not by default. The system defaults to `dry_run: true` with sandbox required. Paper mode connects to exchange testnets only. Live trading with real money would require removing safety guards, which we deliberately make difficult.

### Does this guarantee profits?

No. This is a research tool. Synthetic backtest results are mathematical exercises, not predictions of future performance. The news→crypto correlation hypothesis is unproven.

### Do I need an API key to get started?

No. `ndbot seed-demo` and `ndbot simulate` work entirely offline with synthetic data. API keys are only needed for `ndbot paper` mode.

---

## Technical

### What Python version do I need?

Python 3.11 or higher. Tested on 3.11, 3.12, and 3.13.

### Does it work on Windows?

Yes. The full test suite passes on Windows. Use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

### Does it work on Raspberry Pi 5?

Yes. ndbot is specifically optimised for Pi 5 (ARM64). Docker images build natively. Simulation runs in 3-5 seconds.

### How much memory does it use?

- Simulate mode: ~500MB
- Paper mode: ~1GB
- Walk-forward with 50k candles: ~1.5GB peak

### Why is Sharpe very high / very low?

- Very high (>3): Likely overfitting or very small sample size
- Very low (<0): Strategy loses money at these parameters
- NaN: No trades or no variance in returns

### Why are there 0 trades?

Possible causes:
1. `min_confidence` is too high — lower it to 0.30
2. Confirmation engine rejects all signals — set `confirmation.enabled: false` for testing
3. No events match keywords — check feed domain assignment
4. Max positions reached — increase `max_concurrent_positions`

### Can I use real OHLCV data?

Yes. Use `ndbot backtest` with `--candles-file`:

```bash
ndbot backtest -c config/sample.yaml --candles-file data/BTCUSDT_5m.csv
```

The CSV must have a datetime index and columns: open, high, low, close, volume.

### How do I add a new signal domain?

1. Add the domain to `EventDomain` enum in `feeds/base.py`
2. Create a signal generator in `signals/my_domain.py`
3. Add keyword patterns to `classifier/keyword_classifier.py`
4. Register the generator in `execution/simulate.py`
5. Add config entry in `config/settings.py`
6. Write tests

---

## Data

### Where is data stored?

- SQLite database: `data/ndbot.db`
- Run metrics: `results/run_*_metrics.json`
- Event study charts: `results/event_study_*.png`
- Logs: `logs/ndbot.log`

### How do I export my data?

```bash
# Export trades to CSV
ndbot export --run-id <id> --what trades --format csv

# Export events to JSON
ndbot export --run-id <id> --what events --format json

# Export both
ndbot export --run-id <id> --what both
```

### How do I reset the database?

Delete the database file:
```bash
rm data/ndbot.db
```

The next run will create a fresh database.

### Can I query the database directly?

Yes:
```bash
sqlite3 data/ndbot.db "SELECT * FROM runs ORDER BY start_time DESC LIMIT 5;"
```

---

## Feeds

### Which RSS feeds work best?

High-credibility feeds with clear, specific headlines:
- Reuters Commodities (ENERGY_GEO, weight 1.8)
- OpenAI Blog (AI_RELEASES, weight 2.0)
- Anthropic News (AI_RELEASES, weight 2.0)
- TechCrunch AI (AI_RELEASES, weight 1.5)

### How often should I poll feeds?

- Primary sources: 60 seconds
- Aggregators: 120 seconds
- Official blogs: 300 seconds (post rarely)

Too frequent polling risks rate limiting (HTTP 429).

### What happens if a feed goes down?

The RSS reader retries 3 times with exponential backoff (2s, 4s, 8s). After all retries fail, it returns an empty list and logs an error. Other feeds continue normally.
