# Grid Search

## Purpose

Exhaustively test all combinations of key parameters to find the optimal configuration. Unlike walk-forward (which tests out-of-sample), grid search tests on a single data window.

---

## How It Works

```bash
ndbot grid --config config/sample.yaml --n-events 100 --seed 42
```

### Parameter Space

| Parameter | Values Tested |
|---|---|
| `min_confidence` | 0.30, 0.40, 0.50, 0.60, 0.70 |
| `risk_per_trade` | 0.005, 0.01, 0.015, 0.02, 0.03 |

**Total combinations**: 5 × 5 = 25

### For Each Combination

1. Run a simulation with those parameters
2. Record: total_trades, sharpe_ratio, total_return_pct, max_drawdown_pct, profit_factor, win_rate_pct
3. Save results to the `grid_results` database table

---

## Output

A colour-coded table showing all 25 combinations:

```
Grid Search Results
╔══════════╦══════════╦════════╦═════════╦═════════╦════════╦══════════╗
║ min_conf ║ risk_frac ║ Trades ║ Sharpe  ║ Return% ║ MaxDD% ║ WinRate% ║
╠══════════╬══════════╬════════╬═════════╬═════════╬════════╬══════════╣
║ 0.3      ║ 0.005   ║ 45     ║ 0.4521  ║ 2.1234  ║ 8.123  ║ 55.56   ║
║ 0.3      ║ 0.01    ║ 45     ║ 0.6789  ║ 4.2345  ║ 12.45  ║ 55.56   ║
║ ...      ║ ...     ║ ...    ║ ...     ║ ...     ║ ...    ║ ...     ║
║ 0.7      ║ 0.03    ║ 12     ║ 1.2345  ║ 3.4567  ║ 6.789  ║ 66.67   ║
╚══════════╩══════════╩════════╩═════════╩════════╩════════╩══════════╝

Best params: {'min_confidence': 0.5, 'risk_per_trade': 0.015} | Sharpe=1.2345
```

Green = positive Sharpe, Red = negative Sharpe.

---

## How to Use Grid Results

### 1. Identify the Sharpe-Optimal Parameters

The "best" params are those with the highest Sharpe ratio. But beware:
- High Sharpe with few trades (< 20) is unreliable
- High Sharpe with high drawdown is risky

### 2. Look for Parameter Stability

Good parameters should be surrounded by other good parameters. If changing `min_confidence` from 0.50 to 0.40 causes Sharpe to collapse, the edge is fragile.

### 3. Validate with Walk-Forward

Grid search alone is **in-sample**. Always validate the best parameters with `ndbot walkforward`.

---

## Limitations

| Issue | Explanation |
|---|---|
| **In-sample only** | Best params may overfit to this specific data |
| **Grid is discrete** | Optimal may lie between tested values |
| **Small grid** | 25 combos is minimal; not exhaustive |
| **No interaction effects** | Doesn't test how params interact with market conditions |

---

## Results Storage

All grid results are saved to the `grid_results` SQLite table and can be queried:

```python
from ndbot.storage.database import Database
db = Database("data/ndbot.db")
db.init()
results = db.execute_raw("SELECT * FROM grid_results WHERE run_id = 'grid_my-research-run'")
```
