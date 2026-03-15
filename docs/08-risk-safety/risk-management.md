# Risk Management

## Risk Model: Fixed Fractional

ndbot uses a **fixed fractional risk model** where each trade risks a fixed percentage of current equity.

```
risk_amount = equity × risk_fraction × regime_multiplier × confidence_multiplier
position_size = risk_amount / |entry_price - stop_loss|
```

---

## Risk Parameters

### Per-Trade Risk

| Parameter | Default | Range | Effect |
|---|---|---|---|
| `risk_per_trade` | 1% | 0.1% – 10% | Equity fraction risked per trade |
| `rr_ratio` | 2.0 | 0.5 – ∞ | Reward:risk ratio for take-profit |

**Example**: With $100 equity and 1% risk:
- Risk amount: $1.00
- If stop distance is $500 on BTC:
- Position size: $1.00 / $500 = 0.002 BTC

### Position Sizing Modifiers

| Factor | Values | Purpose |
|---|---|---|
| **Regime multiplier** | LOW=1.25×, NORMAL=1.0×, HIGH=0.6× | Reduce size in volatile markets |
| **Confidence multiplier** | max(0.3, min(1.0, confidence)) | Reduce size for uncertain signals |

### Stop Placement

ATR-based stops adapt to current volatility:

```
LONG:  stop_loss = entry - 1.5 × ATR
SHORT: stop_loss = entry + 1.5 × ATR
take_profit = entry ± (stop_distance × rr_ratio)
```

---

## Portfolio-Level Controls

### Max Concurrent Positions

```yaml
portfolio:
  max_concurrent_positions: 3
```

Prevents over-concentration. New signals are rejected when the limit is reached.

### Daily Loss Limit

```yaml
portfolio:
  max_daily_loss_pct: 0.05  # 5%
```

When cumulative daily losses exceed this threshold:
1. All open positions are closed (reason: `MAX_DAILY_LOSS`)
2. No new positions are opened for the rest of the day
3. Trading resumes at midnight UTC

### Drawdown Circuit Breaker

```yaml
portfolio:
  max_drawdown_pct: 0.15  # 15%
```

When peak-to-trough equity decline exceeds this threshold:
1. All open positions are closed (reason: `MAX_DRAWDOWN`)
2. No new positions are opened
3. Requires manual reset to resume

### Time Stop

```yaml
portfolio:
  time_stop_minutes: 240  # 4 hours
```

Positions are force-closed after the maximum holding period, regardless of PnL. This prevents capital from being tied up indefinitely.

---

## Risk Checks Flow

```
Signal Received
     │
     ▼
[Max positions reached?] ──Yes──→ REJECT
     │ No
     ▼
[Daily loss exceeded?] ──Yes──→ REJECT
     │ No
     ▼
[Drawdown exceeded?] ──Yes──→ REJECT
     │ No
     ▼
[Size > 0?] ──No──→ REJECT (zero price distance)
     │ Yes
     ▼
[Size ≤ max size?] ──No──→ CLAMP to max
     │ Yes
     ▼
APPROVED → Open Position
```

---

## Commission & Slippage

### Commission

```yaml
portfolio:
  commission_rate: 0.001  # 0.1% per side
```

Applied at both entry and exit. Deducted from `realised_pnl`:
```
commission = (entry_price × size + exit_price × size) × commission_rate
realised_pnl = gross_pnl - commission
```

### Slippage

```yaml
portfolio:
  slippage_rate: 0.0005  # 0.05% per side
```

Simulated adverse price movement:
```
actual_entry = market_price × (1 + slippage_rate)  # worse entry
actual_exit = market_price × (1 + slippage_rate)    # worse exit
```

---

## Risk Hierarchy

From strongest to weakest:

1. **Drawdown circuit breaker** — Emergency stop, shuts everything down
2. **Daily loss limit** — Prevents compounding losses in a single day
3. **Max concurrent positions** — Limits exposure concentration
4. **Regime sizing** — Automatically reduces size in volatile markets
5. **Confidence scaling** — Smaller positions for uncertain signals
6. **ATR-based stops** — Adapts stop distance to current volatility
7. **Time stop** — Prevents indefinite capital lock-up
