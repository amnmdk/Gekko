# Safety Guards

ndbot implements multiple layers of safety to prevent accidental financial loss.

---

## Layer 1: Execution Mode Safety

| Setting | Default | Effect |
|---|---|---|
| `mode: simulate` | Yes | No external connections at all |
| `paper.dry_run: true` | Yes | Orders logged but never submitted |
| `paper.require_sandbox: true` | Yes | Refuses if exchange has no testnet |

### To submit testnet orders, you must explicitly:
1. Set `mode: paper`
2. Set `paper.dry_run: false`
3. Keep `paper.require_sandbox: true`
4. Provide testnet API keys

### What happens if both safeguards are disabled:
- `dry_run: false` + `require_sandbox: false` → **RuntimeError raised**
- The engine will not start. This prevents accidental live trading.

---

## Layer 2: Portfolio Circuit Breakers

### Daily Loss Limit
Stops all trading when cumulative daily losses exceed a threshold.

```yaml
portfolio:
  max_daily_loss_pct: 0.05  # Stop after 5% daily loss
```

**Behaviour**: All open positions are force-closed. No new positions opened until next UTC day.

### Drawdown Circuit Breaker
Stops all trading when equity drawdown from peak exceeds a threshold.

```yaml
portfolio:
  max_drawdown_pct: 0.15  # Stop after 15% drawdown from peak
```

**Behaviour**: All positions closed. System halts. Requires manual reset.

---

## Layer 3: Position-Level Protection

### Stop Loss
Every position has an ATR-based stop loss. Cannot be removed.

### Time Stop
Positions auto-close after `time_stop_minutes` (default: 4 hours). Prevents infinite exposure.

### Maximum Size Cap
Position size is capped at `equity / entry_price` — you cannot exceed 100% equity.

---

## Layer 4: Signal Quality Filters

### Confidence Threshold
Signals below `min_confidence` (default: 0.45) are silently dropped.

### Market Confirmation
Signals must pass breakout + volume + volatility checks before a position opens.

### Concurrent Position Limit
Maximum 3 simultaneous positions (default). New signals are rejected when full.

---

## Layer 5: Configuration Validation

### Pydantic v2 Strict Bounds

Every config field has min/max constraints:

| Field | Min | Max |
|---|---|---|
| `initial_capital` | 1.0 | — |
| `risk_per_trade` | 0.001 | 0.1 |
| `max_daily_loss_pct` | 0.001 | 0.5 |
| `max_drawdown_pct` | 0.01 | 0.9 |
| `min_confidence` | 0.0 | 1.0 |
| `commission_rate` | 0.0 | 0.05 |

Invalid values raise `ValidationError` at config load time — the system won't start with bad config.

### Validate-Config Command

```bash
ndbot validate-config -c config/production.yaml --check-feeds
```

Produces a colour-coded health check table with warnings for aggressive settings.

---

## Layer 6: API Safety

### Config PATCH Clamping

Runtime config updates via `PATCH /api/config` are clamped:

| Field | Min | Max |
|---|---|---|
| `tick_interval` | 5 sec | 300 sec |
| `risk_pct` | 0.1% | 10% |
| `min_confidence` | 0% | 100% |
| `max_positions` | 1 | 10 |

### Reset Protection

`POST /api/reset` requires capital ≥ $10. Cannot set to zero.

---

## Safety Checklist for Production

- [ ] `paper.dry_run: true` — Start in dry-run mode
- [ ] `paper.require_sandbox: true` — Always require testnet
- [ ] `max_daily_loss_pct ≤ 0.05` — 5% daily max
- [ ] `max_drawdown_pct ≤ 0.15` — 15% drawdown max
- [ ] `max_concurrent_positions ≤ 3` — Limit concentration
- [ ] `risk_per_trade ≤ 0.02` — Max 2% per trade
- [ ] API keys set via environment, not config file
- [ ] Logs monitored for WARNING/ERROR messages
- [ ] Test with `--duration 60` before long runs
