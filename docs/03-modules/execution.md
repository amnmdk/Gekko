# Execution Module

> `src/ndbot/execution/` — Simulation engine and paper trading engine

---

## SimulationEngine

The simulation engine runs the full pipeline offline with zero external dependencies.

### Execution Flow

```
1. Create run record in database
2. Generate or load events (synthetic or external)
3. Generate or load candles (synthetic or external)
4. For each event (sorted by timestamp):
   a. Save event to database
   b. Advance market data cursor to event time
   c. Classify event (keyword + entity extraction)
   d. Score confidence (Bayesian model)
   e. Get signal generator for event domain
   f. Generate trade signal (if confidence ≥ threshold)
   g. Open position via portfolio engine (if signal passes confirmation + risk)
   h. Advance time 2 hours (simulate exit conditions)
5. Final update pass — check all remaining positions
6. Force-close any still-open positions (TIME_STOP)
7. Save all trades to database
8. Compute performance report
9. Save metrics JSON to results/
10. Close run record
```

### Configuration

```python
engine = SimulationEngine(
    config=bot_config,          # Full BotConfig
    db=database,                # Database instance
    n_events=40,                # Events per domain
    n_candles=500,              # Candle history length
    seed=42,                    # Random seed
    external_candles=None,      # pd.DataFrame for backtest
    external_events=None,       # list[dict] for backtest
)
summary = engine.run()
```

### Determinism

The simulation is **fully deterministic** with a fixed seed:
- Same seed → same synthetic events (identical headlines, timestamps, scores)
- Same seed → same synthetic candles (identical OHLCV values)
- Same seed → same trade decisions → same final equity

This is verified by `test_simulation_deterministic_with_seed` in the test suite.

### Backtest Mode

When `external_candles` and/or `external_events` are provided:
- Events are reconstructed from stored dicts (from DB export or JSON file)
- Candles are loaded from a DataFrame (from CSV file)
- The pipeline runs identically — only the data source changes

---

## PaperEngine

Async engine for paper trading against a real exchange testnet.

### Safety Architecture

```
                  ┌───────────────────────────┐
                  │     PaperEngine            │
                  │                            │
                  │  dry_run = True  ← DEFAULT │
                  │  require_sandbox = True     │
                  └──────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         dry_run=true   dry_run=false    dry_run=false
         sandbox=any    sandbox=true     sandbox=false
              │              │              │
              ▼              ▼              ▼
         LOG ONLY       TESTNET        RuntimeError
         (no orders)    (sandbox       (REFUSED)
                         orders)
```

### Three safety levels:

1. **DRY_RUN=true** (default): All signals are logged but no orders are submitted. The portfolio tracks virtual positions.

2. **DRY_RUN=false, SANDBOX=true**: Orders are submitted to the exchange testnet (e.g., Binance testnet). Real API calls but fake money.

3. **DRY_RUN=false, SANDBOX=false**: **BLOCKED** — raises `RuntimeError`. This prevents accidental live trading.

### Execution Loop

```python
async def run(self, duration_seconds=None):
    while running:
        events = await self._poll_feeds()      # Async RSS poll
        candles = await self._fetch_candles()   # CCXT exchange data
        for event in events:
            classify(event)
            score = confidence_model.score(event)
            signal = generator.generate(event, score)
            if signal and signal passes confirmation:
                portfolio.on_signal(signal)
        portfolio.update()                     # Check exits
        await asyncio.sleep(tick_interval)
```

### Paper Trading Configuration

```yaml
paper:
  exchange_id: "binance"       # CCXT exchange ID
  dry_run: true                # TRUE BY DEFAULT
  require_sandbox: true        # Refuse if no sandbox
  api_key: null                # Set via NDBOT__PAPER__API_KEY
  api_secret: null             # Set via NDBOT__PAPER__API_SECRET
```

### Supported Exchanges

Any CCXT-compatible exchange with testnet/sandbox support:

| Exchange | Sandbox URL | CCXT ID |
|---|---|---|
| Binance | testnet.binance.vision | `binance` |
| Bybit | testnet.bybit.com | `bybit` |
| Kraken | No official sandbox | `kraken` |
| OKX | demo trading | `okx` |
