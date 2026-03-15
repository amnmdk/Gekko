# Interpreting Results

A guide to understanding what the numbers mean and what they don't.

---

## Performance Metrics Explained

### Sharpe Ratio

**What it measures**: Risk-adjusted return. How much return you get per unit of volatility.

```
Sharpe = mean(daily_returns) / std(daily_returns) × √252
```

| Sharpe | Interpretation |
|---|---|
| < 0 | Losing money on average |
| 0 – 0.5 | Poor — barely above random |
| 0.5 – 1.0 | Acceptable for research |
| 1.0 – 2.0 | Good — real edge likely present |
| > 2.0 | Excellent — or suspicious (check for overfitting) |

### Sortino Ratio

Like Sharpe, but only penalises downside volatility:

```
Sortino = mean(returns) / std(negative_returns) × √252
```

Sortino > Sharpe means your gains are more volatile than your losses (good).

### Calmar Ratio

Return relative to worst-case drawdown:

```
Calmar = annualised_return / max_drawdown
```

| Calmar | Interpretation |
|---|---|
| < 0.5 | Returns don't justify the drawdown risk |
| 0.5 – 1.0 | Acceptable |
| > 1.0 | Good risk/return profile |

### Profit Factor

```
Profit Factor = gross_winning_PnL / gross_losing_PnL
```

| PF | Interpretation |
|---|---|
| < 1.0 | Losing money |
| 1.0 – 1.5 | Marginal edge |
| 1.5 – 2.0 | Good |
| > 2.0 | Excellent |
| ∞ | All trades are winners (small sample!) |

### Max Drawdown

The largest peak-to-trough decline in equity:

```
Max DD = max((peak - trough) / peak)
```

| DD | Risk Level |
|---|---|
| < 5% | Very conservative |
| 5 – 15% | Moderate |
| 15 – 25% | Aggressive |
| > 25% | High risk |

### Win Rate

Percentage of trades that are profitable.

| Win Rate | Context |
|---|---|
| 40-50% | Normal for trend-following (relies on big wins) |
| 50-60% | Good for news-based signals |
| > 60% | Excellent or suspicious |

**Important**: Win rate alone means nothing. A 90% win rate with 10× larger losses is still a losing strategy.

### Expectancy

Expected dollar value per trade:

```
Expectancy = (win_rate × avg_win) - (loss_rate × avg_loss)
```

Expectancy must be positive for a viable strategy. Even a small positive expectancy compounds over many trades.

---

## Red Flags

### In Simulation Results

| Red Flag | What It Means |
|---|---|
| Sharpe > 3.0 with synthetic data | Likely overfitting or bug |
| 100% win rate | Sample too small or SL/TP too wide |
| 0 trades | Threshold too high or feeds not generating events |
| Very high drawdown (>30%) | Risk parameters too aggressive |
| PnL precision issues | Check commission/slippage model |

### In Walk-Forward Results

| Red Flag | What It Means |
|---|---|
| IS Sharpe 5× higher than OOS | Severe overfitting |
| All OOS windows negative | Strategy has no edge |
| OOS trades < 10 per window | Insufficient data |
| Increasing DD across windows | Strategy is degrading |

---

## Synthetic vs Real Data

Results from synthetic data are **mathematical exercises**. They tell you:
- ✅ The code works correctly
- ✅ The pipeline processes events end-to-end
- ✅ Risk controls function properly
- ❌ NOT whether the strategy would work with real news
- ❌ NOT whether the correlation hypothesis is valid
- ❌ NOT what real execution slippage would be

To get meaningful results, use `backtest` mode with real OHLCV data and real event histories.

---

## Sample Size Requirements

| Metric | Minimum n | Reliable n |
|---|---|---|
| Win rate | 30 trades | 100+ trades |
| Sharpe ratio | 30 daily returns | 252+ (1 year) |
| Event study t-stat | 30 events | 100+ events |
| Walk-forward window | 30 OOS trades | 50+ OOS trades |

With fewer data points, statistical metrics are noise.
