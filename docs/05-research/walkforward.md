# Walk-Forward Validation

## Purpose

Detect **overfitting** by testing strategy parameters on data they were not trained on. This is the single most important research tool for validating whether a trading strategy has any real edge.

---

## Methodology

### Rolling Window Approach

```
Time →
├─── Train Window (3 years) ───┤── Test Window (1 year) ──┤
                                    ↓ record OOS metrics
              ├─── Train (shifted 90d) ───┤── Test ──┤
                                              ↓ record OOS metrics
                        ├─── Train ───┤── Test ──┤
                                          ↓ record OOS metrics
```

### Steps per Window

1. **Train**: Grid search over `min_confidence` × `risk_per_trade` on the training period
2. **Select**: Choose parameters with the best in-sample Sharpe ratio
3. **Test**: Apply those parameters to the out-of-sample (OOS) test period
4. **Record**: Save OOS Sharpe, return %, max drawdown, trade count
5. **Roll**: Shift the window forward by `step_days` and repeat

### Parameter Grid

| Parameter | Values |
|---|---|
| `min_confidence` | 0.30, 0.40, 0.50, 0.60, 0.70 |
| `risk_per_trade` | 0.005, 0.01, 0.015, 0.02, 0.03 |

Total: 25 combinations tested per window.

---

## Running Walk-Forward

```bash
ndbot walkforward --config config/sample.yaml --n-events 200 --seed 42
```

**Output**:
```
Walk-Forward: my-research-run
╔══════════╦═════════╦═══════════╦═════════╦════════╦═══════╗
║ Window   ║ IS Sharpe ║ OOS Sharpe ║ Return% ║ MaxDD% ║ Trades ║
╠══════════╬═════════╬═══════════╬═════════╬════════╬═══════╣
║ 0        ║ 1.23    ║ 0.45      ║ 3.2%    ║ -8.1%  ║ 23    ║
║ 1        ║ 0.98    ║ 0.12      ║ 1.1%    ║ -12.3% ║ 18    ║
║ 2        ║ 1.45    ║ -0.31     ║ -2.4%   ║ -15.7% ║ 15    ║
╚══════════╩═════════╩═══════════╩═════════╩════════╩═══════╝

Aggregate OOS Metrics
  mean_oos_sharpe           0.087
  mean_oos_return_pct       0.633
  pct_profitable_windows    66.7%
```

---

## Interpreting Results

### Viability Criteria

| Metric | Pass | Fail |
|---|---|---|
| Mean OOS Sharpe | > 0.0 | < 0.0 |
| OOS Sharpe > 0 in N% of windows | > 50% | < 50% |
| Mean OOS Return | > 0% | < 0% |
| Mean OOS Max Drawdown | < 20% | > 20% |
| Min OOS trades per window | ≥ 30 | < 30 (not enough data) |

### Red Flags

1. **IS Sharpe >> OOS Sharpe**: Classic overfitting. The parameters look great on training data but fail on new data.
2. **All windows unprofitable**: The strategy has no edge at these parameters.
3. **OOS trades < 10 per window**: Insufficient data to draw conclusions.
4. **Increasing drawdown across windows**: Strategy degradation over time (non-stationarity).

### Good Signs

1. **OOS Sharpe > 0.5 across 3+ windows**: Real signal present.
2. **IS and OOS Sharpe within 2× of each other**: Parameters are robust.
3. **Consistent win rate across windows**: Stable edge.

---

## Configuration

```yaml
research:
  train_days: 1095    # 3 years
  test_days: 365      # 1 year
  step_days: 90       # Quarterly roll
```

### Tuning Tips

- **Shorter train period** (e.g., 365d): More windows, faster iteration, but less data per train
- **Shorter test period** (e.g., 90d): More granular OOS metrics, but fewer trades per window
- **Smaller step** (e.g., 30d): More overlap between windows, smoother results

---

## Limitations

| Limitation | Impact |
|---|---|
| Grid size | 25 combos may overfit even in-sample |
| Stationarity assumption | Signal quality may change over time |
| Transaction costs | Modelled via commission/slippage but may underestimate |
| Synthetic data | Walk-forward on synthetic data tests the code, not the strategy |
| Sample size | Need >30 OOS trades per window for statistical meaning |
