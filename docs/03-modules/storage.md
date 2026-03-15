# Storage Module

> `src/ndbot/storage/` — SQLAlchemy ORM and database abstraction

---

## Overview

All persistent data is stored in **SQLite** via SQLAlchemy. The database stores:
- News events (with classification metadata)
- Trade records (with full position lifecycle)
- Run metadata (with performance summary)
- Research results (walk-forward windows, grid search results)

---

## Database Tables

### `events`

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-increment |
| `event_id` | String | SHA-256 hash (unique per event) |
| `run_id` | String | Which run ingested this event |
| `domain` | String | ENERGY_GEO, AI_RELEASES, UNKNOWN |
| `headline` | String | Event title |
| `summary` | Text | Full event text |
| `source` | String | Feed name |
| `url` | String | Original article URL |
| `published_at` | DateTime | Publication time (UTC) |
| `ingested_at` | DateTime | Ingestion time (UTC) |
| `credibility_weight` | Float | Source reliability [0, 2] |
| `keywords_matched` | JSON | List of matched keywords |
| `sentiment_score` | Float | [-1, +1] |
| `importance_score` | Float | [0, 1] |
| `entities` | JSON | {ORG: [...], LOCATION: [...]} |

### `trades`

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-increment |
| `position_id` | String | Unique position hash |
| `run_id` | String | Which run opened this trade |
| `symbol` | String | e.g., BTC/USDT |
| `direction` | String | LONG or SHORT |
| `domain` | String | Signal domain |
| `signal_id` | String | Triggering signal ID |
| `event_id` | String | Triggering event ID |
| `entry_price` | Float | Entry price (with slippage) |
| `exit_price` | Float | Exit price (null if open) |
| `size` | Float | Position size |
| `stop_loss` | Float | Stop loss level |
| `take_profit` | Float | Take profit level |
| `entry_time` | DateTime | Position open time |
| `exit_time` | DateTime | Position close time |
| `holding_minutes` | Integer | Max holding period |
| `status` | String | OPEN, CLOSED, CANCELLED |
| `close_reason` | String | TAKE_PROFIT, STOP_LOSS, etc. |
| `realised_pnl` | Float | Net PnL after commission |
| `commission_paid` | Float | Total commission both sides |
| `risk_amount` | Float | Capital at risk |
| `confidence` | Float | Signal confidence score |

### `runs`

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-increment |
| `run_id` | String | Unique run identifier |
| `run_name` | String | Human-readable name |
| `mode` | String | simulate, backtest, paper |
| `start_time` | DateTime | Run start |
| `end_time` | DateTime | Run end |
| `initial_capital` | Float | Starting equity |
| `final_equity` | Float | Ending equity |
| `total_trades` | Integer | Number of closed trades |
| `total_pnl` | Float | Net PnL |
| `sharpe_ratio` | Float | Risk-adjusted return |
| `max_drawdown_pct` | Float | Maximum drawdown |
| `config_snapshot` | JSON | Full config at run time |

### `walkforward_results`

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-increment |
| `run_id` | String | Walk-forward run ID |
| `window_idx` | Integer | Window number |
| `train_start` / `train_end` | DateTime | Training period |
| `test_start` / `test_end` | DateTime | Test period |
| `best_min_confidence` | Float | Optimal confidence |
| `best_risk_per_trade` | Float | Optimal risk fraction |
| `is_sharpe` | Float | In-sample Sharpe |
| `oos_sharpe` | Float | Out-of-sample Sharpe |
| `oos_return_pct` | Float | OOS return |
| `oos_max_dd` | Float | OOS max drawdown |
| `oos_trades` | Integer | OOS trade count |

### `grid_results`

| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Auto-increment |
| `run_id` | String | Grid search run ID |
| `min_confidence` | Float | Parameter value |
| `risk_per_trade` | Float | Parameter value |
| `total_trades` | Integer | Trades at these params |
| `sharpe_ratio` | Float | Sharpe at these params |
| `total_return_pct` | Float | Return % |
| `max_drawdown_pct` | Float | Max drawdown |
| `profit_factor` | Float | Profit factor |
| `win_rate_pct` | Float | Win rate % |

---

## Database API

### Events

```python
db.save_event(event: NewsEvent, run_id: str) -> None
db.get_events(run_id=None, domain=None, limit=1000) -> list[dict]
```

### Trades

```python
db.save_trade(position: Position, run_id: str) -> None
db.get_trades(run_id=None, limit=500) -> list[dict]
```

### Runs

```python
db.create_run(run_id, run_name, mode, initial_capital, config_snapshot) -> None
db.close_run(run_id, final_equity, total_trades, total_pnl, sharpe, max_dd) -> None
db.get_runs(limit=50) -> list[dict]
```

### Research

```python
db.save_walkforward_result(run_id, window: dict) -> None
db.save_grid_result(run_id, params: dict, metrics: dict) -> None
```

---

## Deduplication

Events are deduplicated at two levels:
1. **In-memory**: `BaseFeed._seen_ids` set prevents re-ingestion during a session
2. **Database**: The `save_event` method checks for existing `event_id` before insert

This is verified by `test_database_deduplicates_events` — inserting 5 identical events stores exactly 1 row.
