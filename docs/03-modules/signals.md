# Signals Module

> `src/ndbot/signals/` — Confidence scoring, signal generation, and market confirmation

---

## Overview

The signals module converts enriched `NewsEvent` objects into actionable `TradeSignal` objects through three stages:

1. **Confidence Model** — Score event reliability (0.05 to 0.95)
2. **Signal Generators** — Determine trade direction per domain
3. **Confirmation Engine** — Validate against market conditions

---

## Confidence Model

### Algorithm: Bayesian Log-Odds Update

Starting from a prior of 0.5 (maximum uncertainty), five evidence dimensions shift the log-odds:

```
log_odds = 0  (prior = 0.5)

log_odds += logit(credibility_weight / 2.0)    # Source reliability
log_odds += logit(importance_score)             # Entity significance
log_odds += logit(0.5 + tanh(cluster/3) × 0.3) # Clustering density
log_odds += logit(0.5 + tanh(corr/2) × 0.25)   # Corroboration
log_odds += logit(0.5 + |sentiment| × 0.3)      # Sentiment strength

confidence = sigmoid(log_odds)
confidence = clip(confidence, 0.05, 0.95)
```

### Memory Window

The model maintains a 60-minute sliding window of recent events:
- **Clustering density**: Counts events sharing ≥1 keyword with the current event
- **Corroboration**: Counts distinct sources reporting similar stories (≥2 shared keywords, different source name)
- Events are scored **before** being added to memory (no self-counting)

### Confidence Score Interpretation

| Range | Meaning | Action |
|---|---|---|
| 0.05 – 0.30 | Very low confidence | No signal generated |
| 0.30 – 0.45 | Low confidence | Below default threshold |
| **0.45 – 0.65** | **Moderate confidence** | **Signal generated (default threshold)** |
| 0.65 – 0.80 | High confidence | Signal with larger position size |
| 0.80 – 0.95 | Very high confidence | Maximum position size |

---

## TradeSignal

```python
@dataclass
class TradeSignal:
    signal_id: str
    domain: str                # "ENERGY_GEO" | "AI_RELEASES"
    direction: SignalDirection  # LONG | SHORT | FLAT
    symbol: str                # "BTC/USDT"
    confidence: float          # [0, 1]
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    holding_minutes: int
    risk_fraction: float
    created_at: datetime
    event_id: str
    event_headline: str
    keywords: list[str]
    regime: str                # "LOW" | "NORMAL" | "HIGH"
    confirmed: bool
    metadata: dict
```

---

## Signal Generators

### EnergyGeoSignalGenerator

Handles `ENERGY_GEO` domain events.

**Direction Logic**:

| Event Type | Direction | Rationale |
|---|---|---|
| Sanctions, embargo, disruption | **SHORT** | Supply reduction → price spike → short after |
| Attack, blockade, chokepoint threat | **SHORT** | Geopolitical risk → flight to safety |
| Production increase, deal, agreement | **LONG** | Supply stability → bullish momentum |
| Infrastructure expansion | **LONG** | Long-term supply growth |

**Gate**: Only fires if `confidence ≥ min_confidence` AND domain matches.

### AIReleasesSignalGenerator

Handles `AI_RELEASES` domain events.

**Direction Logic**:

| Event Type | Direction | Rationale |
|---|---|---|
| Product launch, partnership | **LONG** | Market excitement → risk-on |
| Model release, breakthrough | **LONG** | Sector momentum |
| Security incident, breach | **SHORT** | Risk-off sentiment |
| Service outage, failure | **SHORT** | Negative momentum |

---

## Confirmation Engine

After a signal is generated, it must pass market confirmation before a position is opened.

### Three Conditions (all must pass)

1. **Breakout Check**
   - LONG: `current_price > max(recent_highs) × (1 + breakout_threshold)`
   - SHORT: `current_price < min(recent_lows) × (1 - breakout_threshold)`
   - Default threshold: 0.2%

2. **Volume Spike Check**
   - `current_volume > mean(recent_volumes) × volume_spike_multiplier`
   - Default multiplier: 1.5×

3. **Volatility Expansion Check**
   - `current_ATR > mean(recent_ATR) × volatility_expansion_multiplier`
   - Default multiplier: 1.3×

Lookback period: 20 candles (configurable via `lookback_candles`).

### Why Confirmation Matters

Without confirmation, many keyword-matched events would generate trades that go nowhere. Confirmation ensures the market is actually reacting to the news before committing capital.

If confirmation is disabled (`confirmation.enabled: false`), all signals pass through directly — useful for research but risky for live trading.
