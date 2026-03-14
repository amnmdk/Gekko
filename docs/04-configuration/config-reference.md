# Configuration Reference

All configuration is defined in a single YAML file. See `config/sample.yaml` for a complete example.

---

## Top-Level

| Field | Type | Default | Description |
|---|---|---|---|
| `run_name` | string | `"ndbot-run"` | Human-readable label for this run |
| `mode` | enum | `"simulate"` | Execution mode: `simulate`, `backtest`, `paper` |
| `log_level` | string | `"INFO"` | Logging verbosity: DEBUG, INFO, WARNING, ERROR |

---

## `market`

Market data configuration.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `symbol` | string | `"BTC/USDT"` | — | Trading pair (CCXT format) |
| `timeframe` | string | `"5m"` | — | Candle timeframe |
| `candle_window` | int | `200` | ≥ 50 | Candles to keep in memory |
| `atr_period` | int | `14` | ≥ 5 | ATR calculation window |
| `atr_percentile_window` | int | `100` | ≥ 30 | Regime percentile lookback |
| `ma_short` | int | `20` | ≥ 5 | Short moving average period |
| `ma_long` | int | `50` | ≥ 10 | Long moving average period |

---

## `feeds[]`

RSS feed configuration. Array of feed objects.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `name` | string | *required* | — | Unique feed identifier |
| `url` | string | *required* | — | RSS/Atom feed URL |
| `domain` | enum | *required* | — | `ENERGY_GEO` or `AI_RELEASES` |
| `poll_interval_seconds` | int | `60` | ≥ 10 | Seconds between polls |
| `enabled` | bool | `true` | — | Whether to poll this feed |
| `credibility_weight` | float | `1.0` | 0.0 – 2.0 | Source reliability weight |

---

## `signals[]`

Signal generator configuration. One entry per domain.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `domain` | enum | *required* | — | `ENERGY_GEO` or `AI_RELEASES` |
| `enabled` | bool | `true` | — | Whether to generate signals |
| `min_confidence` | float | `0.45` | 0.0 – 1.0 | Minimum confidence to emit signal |
| `holding_minutes` | int | `60` | ≥ 1 | Maximum position hold time |
| `risk_per_trade` | float | `0.01` | 0.001 – 0.1 | Fraction of equity risked |
| `rr_ratio` | float | `2.0` | ≥ 0.5 | Take-profit / stop-loss ratio |

### Signal Tuning Guide

| Parameter | Conservative | Moderate | Aggressive |
|---|---|---|---|
| `min_confidence` | 0.65 | 0.45 | 0.30 |
| `risk_per_trade` | 0.005 | 0.01 | 0.03 |
| `rr_ratio` | 3.0 | 2.0 | 1.5 |
| `holding_minutes` | 120 | 60 | 30 |

---

## `confirmation`

Market confirmation engine settings.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | — | Require market confirmation |
| `breakout_threshold` | float | `0.002` | 0.0 – 0.05 | Breakout % above recent high |
| `volume_spike_multiplier` | float | `1.5` | ≥ 1.0 | Volume vs average multiplier |
| `volatility_expansion_multiplier` | float | `1.3` | ≥ 1.0 | ATR vs average multiplier |
| `lookback_candles` | int | `20` | ≥ 5 | Reference period for checks |

---

## `portfolio`

Portfolio and risk management.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `initial_capital` | float | `100.0` | ≥ 1.0 | Starting equity (USD) |
| `currency` | string | `"USD"` | — | Base currency label |
| `max_concurrent_positions` | int | `3` | ≥ 1 | Max simultaneous open positions |
| `max_daily_loss_pct` | float | `0.05` | 0.001 – 0.5 | Daily loss limit (fraction) |
| `max_drawdown_pct` | float | `0.15` | 0.01 – 0.9 | Drawdown circuit breaker |
| `time_stop_minutes` | int | `240` | ≥ 5 | Force close after N minutes |
| `commission_rate` | float | `0.001` | 0.0 – 0.05 | Commission per side |
| `slippage_rate` | float | `0.0005` | 0.0 – 0.01 | Simulated slippage per side |

---

## `storage`

Database configuration.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `db_path` | string | `"data/ndbot.db"` | — | SQLite database file path |
| `events_retention_days` | int | `365` | ≥ 1 | Event retention period |

---

## `paper`

Paper trading configuration. Only used in `paper` mode.

| Field | Type | Default | Description |
|---|---|---|---|
| `exchange_id` | string | `"binance"` | CCXT exchange identifier |
| `dry_run` | bool | `true` | **TRUE BY DEFAULT** — no real orders |
| `require_sandbox` | bool | `true` | Refuse if sandbox unavailable |
| `api_key` | string | `null` | Exchange API key (use env var) |
| `api_secret` | string | `null` | Exchange API secret (use env var) |

---

## `research`

Research tool parameters.

| Field | Type | Default | Range | Description |
|---|---|---|---|---|
| `pre_event_candles` | int | `12` | ≥ 1 | Candles before event in study |
| `post_event_candles` | int | `48` | ≥ 1 | Candles after event in study |
| `train_days` | int | `1095` | ≥ 30 | Walk-forward training window |
| `test_days` | int | `365` | ≥ 7 | Walk-forward test window |
| `step_days` | int | `90` | ≥ 7 | Walk-forward roll step |

---

## Pydantic Validation

All fields are validated by Pydantic v2 with strict bounds:
- Out-of-range values raise `ValidationError` at config load time
- `mode` must be exactly `simulate`, `backtest`, or `paper`
- `paper.dry_run=false` triggers a safety warning
- Empty `extra` dict allows arbitrary extension fields
