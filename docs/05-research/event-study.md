# Event Study

## Purpose

Measure the **average price impact** of news events at multiple time horizons. This answers: "When an energy geopolitics event occurs, how much does the price move in the next 5 minutes? 15 minutes? 1 hour? 4 hours?"

---

## Methodology

### 1. Event Alignment

For each event E_i at time t_i:
- Find the nearest candle in the OHLCV data
- Extract a window: `[t_i - pre_event_candles, t_i + post_event_candles]`
- Default: 12 candles before (1h at 5m), 48 candles after (4h at 5m)

### 2. Return Calculation

Compute normalised returns at four horizons:

| Horizon | Candles | Time (at 5m) |
|---|---|---|
| H1 | 1 candle | 5 minutes |
| H2 | 3 candles | 15 minutes |
| H3 | 12 candles | 1 hour |
| H4 | 48 candles | 4 hours |

```
return_h = (close[t_i + h] - close[t_i]) / close[t_i]
```

### 3. Volatility Expansion

Measure whether volatility increases after the event:

```
vol_expansion = std(returns_post) / std(returns_pre)
```

A ratio > 1.0 indicates the event caused increased market activity.

### 4. Aggregation

For all events:
- **Mean return** at each horizon
- **t-statistic**: `mean / (std / sqrt(n))`
- **% positive**: Fraction of events with positive returns
- **Count**: Number of events measured

---

## Running an Event Study

```bash
ndbot event-study --config config/sample.yaml --n-events 30 --seed 42
```

**Output**:
```
Event Study Results — 60 events
  5m_return    mean=+0.0012%  t=1.23  pct+=52.0%  n=60
  15m_return   mean=+0.0034%  t=1.87  pct+=55.0%  n=60
  1h_return    mean=+0.0089%  t=2.14  pct+=58.0%  n=60
  4h_return    mean=+0.0142%  t=1.96  pct+=54.0%  n=60
```

A PNG chart is also saved to the output directory.

---

## Interpreting Results

### t-statistic Guide

| t-stat | p-value (approx) | Interpretation |
|---|---|---|
| < 1.0 | > 0.30 | No evidence of price impact |
| 1.0 – 1.65 | 0.10 – 0.30 | Weak evidence (not significant) |
| 1.65 – 2.0 | 0.05 – 0.10 | Marginal evidence |
| **> 2.0** | **< 0.05** | **Suggestive evidence** |
| > 2.58 | < 0.01 | Strong evidence |

**Important**: With synthetic data, these numbers are exercises in statistics, not evidence of a tradeable edge.

### What to Look For

1. **Positive mean return with t > 2.0 at short horizons** (5m, 15m) — Suggests immediate price reaction
2. **Return decay at longer horizons** — Normal; the immediate impact fades
3. **Vol expansion > 1.3** — Market is reacting to the news event
4. **pct_positive > 55%** — More events move price up than down (for LONG signals)

---

## Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| **Selection bias** | We only study events we ingested | Use multiple RSS sources |
| **Look-ahead bias** | Keywords in headlines create label leakage | Be aware; test with OOS data |
| **Small samples** | n < 50 → unreliable t-statistics | Generate more events; use longer history |
| **Confounding** | Other events in the post-window | Shorter horizons are cleaner |
| **Transaction costs** | Not modelled in event study | Use `simulate` to test with commission |
| **Synthetic data** | No real market microstructure | Use `backtest` with real OHLCV data |

---

## Configuration

```yaml
research:
  pre_event_candles: 12    # 1 hour before (at 5m candles)
  post_event_candles: 48   # 4 hours after
```

Adjust these for different timeframes or study windows.
