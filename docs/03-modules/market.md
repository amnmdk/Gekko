# Market Data Module

> `src/ndbot/market/` — OHLCV data, regime detection, synthetic candles

---

## Overview

The market module provides:
- **Market data access** — Both live (CCXT) and synthetic candle data
- **Regime detection** — Volatility and trend classification
- **Synthetic candle generation** — GBM+GARCH model for testing

---

## MarketDataFeed

Unified interface for accessing OHLCV candle data.

### Modes

| Mode | Data Source | Used By |
|---|---|---|
| `load_synthetic()` | `SyntheticCandleGenerator` | `simulate` command |
| `load_dataframe()` | External CSV/DataFrame | `backtest` command |
| `fetch_candles()` | CCXT exchange API | `paper` command |

### Key Methods

```python
class MarketDataFeed:
    def current_price(self) -> float       # Latest close price
    def current_atr(self) -> float         # Latest ATR value
    def volatility_regime(self) -> VolatilityRegime  # LOW | NORMAL | HIGH
    def candles(self) -> pd.DataFrame      # Full candle history
```

### Configuration

```yaml
market:
  symbol: "BTC/USDT"
  timeframe: "5m"
  candle_window: 300          # Keep 300 candles in memory
  atr_period: 14              # ATR calculation window
  atr_percentile_window: 100  # For regime percentile thresholds
  ma_short: 20                # Short moving average
  ma_long: 50                 # Long moving average
```

---

## RegimeDetector

Classifies current market conditions into volatility and trend regimes.

### Volatility Regimes

Based on ATR percentile relative to recent history:

| Regime | Condition | Position Sizing Multiplier |
|---|---|---|
| `LOW` | ATR < 25th percentile | 1.25× (larger positions) |
| `NORMAL` | 25th ≤ ATR ≤ 75th percentile | 1.0× (standard) |
| `HIGH` | ATR > 75th percentile | 0.6× (smaller positions) |

### Trend Regimes

Based on moving average crossover:

| Regime | Condition |
|---|---|
| `UPTREND` | MA_short > MA_long |
| `DOWNTREND` | MA_short < MA_long |
| `SIDEWAYS` | MA_short ≈ MA_long (within 0.1%) |

### Technical Indicators Added

The `add_indicators()` method enriches a candle DataFrame with:

| Column | Description |
|---|---|
| `atr` | Average True Range (14-period) |
| `atr_pct` | ATR as % of close price |
| `ma_short` | 20-period simple moving average |
| `ma_long` | 50-period simple moving average |
| `volume_sma` | 20-period volume moving average |

---

## SyntheticCandleGenerator

Generates realistic OHLCV candles using a **Geometric Brownian Motion + GARCH(1,1)** model.

### Model

```
price[t] = price[t-1] × exp(drift + σ[t] × Z[t])
```

Where:
- `drift`: Small positive drift (simulates long-term appreciation)
- `σ[t]`: Time-varying volatility from GARCH(1,1)
- `Z[t]`: Standard normal random variable

OHLCV construction:
- `open` = previous `close`
- `high` = `max(open, close) × (1 + |ε|)` where ε ~ N(0, σ_wick)
- `low` = `min(open, close) × (1 - |ε|)` where ε ~ N(0, σ_wick)
- `volume` = lognormal distribution with mean proportional to |return|

### Usage

```python
from ndbot.market.synthetic_candles import SyntheticCandleGenerator

gen = SyntheticCandleGenerator(symbol="BTC/USDT", timeframe_minutes=5, seed=42)
candles = gen.generate(count=500, start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
```

### Shock Times

The generator accepts optional `shock_times` — timestamps where synthetic events occur. At these times, volatility is temporarily elevated to simulate real market reactions to news.

### Determinism

Fixed `seed` → identical candles every time. This is critical for reproducible research and deterministic test assertions.
