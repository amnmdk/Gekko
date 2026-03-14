# Portfolio Module

> `src/ndbot/portfolio/` — Position lifecycle, risk engine, performance metrics

---

## Overview

The portfolio module manages the complete trade lifecycle:

1. **Risk Engine** — Pre-trade checks + position sizing
2. **Portfolio Engine** — Open/close positions, track equity
3. **Position** — Individual position state machine
4. **Metrics** — Sharpe, Sortino, Calmar, drawdown calculations

---

## Position Lifecycle

```
                    TradeSignal
                        │
                        ▼
              ┌─────────────────┐
              │    OPEN          │
              │                  │
              │  entry_price     │
              │  size            │
              │  stop_loss       │
              │  take_profit     │
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     Stop Loss    Take Profit   Time Stop
          │            │            │
          └────────────┼────────────┘
                       │
              ┌─────────────────┐
              │    CLOSED        │
              │                  │
              │  exit_price      │
              │  realised_pnl    │
              │  close_reason    │
              └──────────────────┘
```

### Close Reasons

| Reason | Trigger |
|---|---|
| `TAKE_PROFIT` | Price reaches TP level |
| `STOP_LOSS` | Price crosses SL level |
| `TIME_STOP` | Position held > `holding_minutes` |
| `MAX_DAILY_LOSS` | Cumulative daily PnL exceeds limit |
| `MAX_DRAWDOWN` | Portfolio drawdown exceeds circuit breaker |
| `MANUAL` | Manual close (paper mode only) |

---

## Risk Engine

### Pre-Trade Checks

Before any position is opened, the risk engine verifies:

1. **Max Concurrent Positions**: `n_open < max_concurrent_positions` (default: 3)
2. **Daily Loss Limit**: `today_pnl > -(equity × max_daily_loss_pct)` (default: 5%)
3. **Drawdown Circuit Breaker**: `drawdown < max_drawdown_pct` (default: 15%)

If any check fails, the signal is rejected with a logged reason.

### Position Sizing: Fixed Fractional Risk

```
stop_distance = 1.5 × ATR
risk_amount = equity × risk_fraction × regime_mult × confidence_mult
size = risk_amount / stop_distance
```

| Factor | Formula | Effect |
|---|---|---|
| `risk_fraction` | From signal config (default 1%) | Base risk |
| `regime_mult` | LOW=1.25, NORMAL=1.0, HIGH=0.6 | Adapt to volatility |
| `confidence_mult` | max(0.3, min(1.0, confidence)) | Scale by conviction |

### Stop Placement

ATR-based stops:
- **LONG**: `stop = entry - 1.5 × ATR`
- **SHORT**: `stop = entry + 1.5 × ATR`
- **Take-Profit**: `TP = entry ± (stop_distance × rr_ratio)`

If ATR is zero (e.g., flat candles), fallback to 1% of entry price.

---

## Portfolio Engine

Central orchestrator for all position management.

### Signal Processing Flow

```python
def on_signal(self, signal: TradeSignal) -> Optional[Position]:
    # 1. Skip FLAT signals
    # 2. Get current market state (price, ATR, regime)
    # 3. Run confirmation engine (if enabled)
    # 4. Run risk engine sizing
    # 5. Open position (if approved)
    # 6. Apply entry slippage
```

### Position Monitoring

Every `update()` tick checks all open positions:

```python
def update(self, current_time) -> list[Position]:
    for pos in open_positions:
        if should_stop_loss(current_price) → close(STOP_LOSS)
        if should_take_profit(current_price) → close(TAKE_PROFIT)
        if is_expired(current_time) → close(TIME_STOP)
        if daily_loss_exceeded → close(MAX_DAILY_LOSS)
        if drawdown_exceeded → close(MAX_DRAWDOWN)
```

### Slippage Model

Entry and exit prices are adjusted by the slippage rate:
```
actual_price = market_price × (1 + slippage_rate)
```
Default: 0.05% per side.

---

## Performance Metrics

The `PortfolioMetrics.compute()` method calculates:

| Metric | Formula | Interpretation |
|---|---|---|
| **Total PnL** | Σ(realised_pnl) | Absolute profit/loss |
| **Return %** | (final_equity / initial - 1) × 100 | Percentage return |
| **Win Rate** | winning_trades / total_trades | Fraction of profitable trades |
| **Profit Factor** | gross_profit / gross_loss | > 1.5 is good; ∞ if no losses |
| **Sharpe Ratio** | mean(returns) / std(returns) × √252 | Risk-adjusted return (> 1.0 good) |
| **Sortino Ratio** | mean(returns) / downside_std × √252 | Downside risk-adjusted (> 1.5 good) |
| **Calmar Ratio** | annualised_return / max_drawdown | Return per drawdown (> 1.0 good) |
| **Max Drawdown** | max(peak - trough) / peak | Largest equity decline |
| **Expectancy** | (win_rate × avg_win) - (loss_rate × avg_loss) | Expected $ per trade |

### Special Cases

- **profit_factor = ∞**: All trades are winners (no losses). Mathematically valid.
- **Sharpe = 0**: No variance in returns or no trades.
- **Calmar = 0**: No drawdown (extremely unlikely in practice).
