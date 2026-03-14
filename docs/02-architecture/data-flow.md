# Data Flow

## Event Lifecycle

An event passes through the following stages from ingestion to trade execution:

### Stage 1: Ingestion

```
RSS Feed URL → aiohttp GET → feedparser → NewsEvent dataclass
```

- **Input**: Raw XML from RSS/Atom feed
- **Output**: `NewsEvent` with fields: `event_id`, `domain`, `headline`, `summary`, `source`, `url`, `published_at`, `credibility_weight`, `raw_tags`
- **Deduplication**: `event_id` is a SHA-256 hash of `(source, url, headline)` — seen IDs are tracked in memory

### Stage 2: Classification

```
NewsEvent → KeywordClassifier.enrich() → EntityExtractor.enrich()
```

- **Keyword Classifier**: Scans headline + summary against domain-specific keyword dictionaries
  - Sets `domain`, `sentiment_score`, `importance_score`, `keywords_matched`
  - Sentiment: -1.0 (bearish) to +1.0 (bullish)
- **Entity Extractor**: Pattern-based NER on headline + summary
  - Extracts `ORG`, `LOCATION`, `CHOKEPOINT` entities
  - Updates `entities` dict on the NewsEvent

### Stage 3: Confidence Scoring

```
NewsEvent → ConfidenceModel.score() → float ∈ [0.05, 0.95]
```

Five evidence dimensions update log-odds from a 0.5 prior:

1. **Source credibility**: `credibility_weight / 2.0` → logit
2. **Importance score**: `importance_score` → logit
3. **Clustering density**: Count of recent events sharing keywords → `tanh(n/3)` boost
4. **Corroboration**: Distinct sources reporting similar → `tanh(n/2)` boost
5. **Sentiment magnitude**: `|sentiment_score| × 0.3` → linear boost

Memory window: 60 minutes (configurable). Events older than window are pruned.

### Stage 4: Signal Generation

```
(NewsEvent, confidence) → SignalGenerator.generate() → TradeSignal | None
```

- **Gate**: `confidence ≥ min_confidence` (from config, default 0.45)
- **Direction**: Determined by keyword polarity
  - ENERGY_GEO: sanctions/disruption → SHORT, production/supply → LONG
  - AI_RELEASES: launch/announcement → LONG, incident/breach → SHORT
- **Output**: `TradeSignal` with `direction`, `symbol`, `confidence`, `risk_fraction`, `holding_minutes`

### Stage 5: Market Confirmation

```
TradeSignal → ConfirmationEngine.check(signal, candles) → ConfirmationResult
```

Three conditions must be met (all configurable):

1. **Breakout**: Price exceeds recent high/low by `breakout_threshold` (0.2%)
2. **Volume Spike**: Current volume > `volume_spike_multiplier` × 20-candle average (1.5×)
3. **Volatility Expansion**: ATR > `volatility_expansion_multiplier` × recent ATR (1.3×)

If any condition fails, the signal is rejected (logged, not traded).

### Stage 6: Risk Sizing

```
TradeSignal → RiskEngine.compute_sizing() → SizingResult
```

- **Pre-trade checks**: max concurrent positions, daily loss limit, drawdown circuit breaker
- **Stop placement**: ATR-based — `stop = entry ± 1.5 × ATR`
- **Take-profit**: `TP = entry ± (stop_distance × rr_ratio)`
- **Position size**: `size = (equity × risk_fraction × regime_mult × conf_mult) / price_diff`
- **Regime multiplier**: LOW=1.25×, NORMAL=1.0×, HIGH=0.6×
- **Cap**: Size never exceeds 100% of equity / entry_price

### Stage 7: Position Lifecycle

```
SizingResult → PortfolioEngine → Position (OPEN → CLOSED)
```

Exit conditions checked every update tick:
1. **Stop Loss**: Price crosses stop level
2. **Take Profit**: Price reaches TP level
3. **Time Stop**: Position held longer than `holding_minutes`
4. **Daily Loss**: Cumulative daily PnL exceeds `max_daily_loss_pct`
5. **Drawdown**: Portfolio drawdown exceeds `max_drawdown_pct`

### Stage 8: Persistence

```
Position + NewsEvent → Database → SQLite
```

All events, trades, and run metadata are saved to SQLite via SQLAlchemy ORM. Per-run metrics JSON is also saved to `results/`.

---

## Data Types Summary

| Type | Key Fields | Created By |
|---|---|---|
| `NewsEvent` | event_id, domain, headline, confidence, sentiment | FeedManager |
| `TradeSignal` | direction, symbol, confidence, risk_fraction | SignalGenerator |
| `SizingResult` | approved, size, stop_loss, take_profit | RiskEngine |
| `Position` | entry_price, size, SL, TP, realised_pnl | PortfolioEngine |
| `PerformanceReport` | sharpe, sortino, max_drawdown, win_rate | PortfolioMetrics |
