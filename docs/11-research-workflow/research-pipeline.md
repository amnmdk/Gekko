---
title: Research Workflow Pipeline
---

# Research Workflow Pipeline

The ndbot framework follows a **7-stage quantitative research pipeline** that ensures scientific rigour and prevents common pitfalls (look-ahead bias, overfitting, survivorship bias).

## Pipeline Stages

```
1. Hypothesis Generation
        │
        ▼
2. Event Study Analysis
        │
        ▼
3. Backtest (with realistic costs)
        │
        ▼
4. Walk-Forward Validation (OOS)
        │
        ▼
5. Monte Carlo Robustness
        │
        ▼
6. Simulation (full pipeline)
        │
        ▼
7. Paper Trading (live sandbox)
```

---

## Stage 1 — Hypothesis Generation

**Goal:** Form a testable hypothesis about market response to news events.

Example hypotheses:
- *"Energy chokepoint disruption events cause BTC/USDT to rise 0.5% within 1 hour"*
- *"AI model release announcements cause short-term volatility expansion"*

**Rules:**
- Hypothesis must be falsifiable
- Define expected direction, magnitude, and time horizon
- Document the economic reasoning

---

## Stage 2 — Event Study

**Command:** `./launch.sh event-study` or `launch.bat event-study`

**What it does:**
- Aligns candle windows around each historical event
- Computes returns at 5m, 15m, 1h, 4h horizons
- Calculates mean, median, t-statistic, probability of positive move
- Computes volatility expansion ratio (post/pre event)
- Breaks down results by event type (domain)
- Computes time-to-peak impact

**Outputs:** `results/event_study_*.json`, `*.csv`, `*.png`

**Decision gate:** Proceed only if t-stat > 1.5 and directional consistency > 55%.

---

## Stage 3 — Backtest

**Command:** `./launch.sh backtest`

**What it does:**
- Replays events chronologically through the full signal pipeline
- Applies realistic transaction costs (commission + slippage + spread)
- Uses ATR-based stop-loss and take-profit
- Applies regime-aware position sizing
- Computes full performance metrics (Sharpe, Sortino, risk of ruin, etc.)

**Bias prevention:**
- All signals use only information available at time *t* (no look-ahead)
- Candles are processed in order
- Events are timestamped and sorted

**Decision gate:** Sharpe > 0.5, profit factor > 1.2, max drawdown < 15%.

---

## Stage 4 — Walk-Forward Validation

**Command:** `./launch.sh walkforward`

**What it does:**
- Splits data into rolling train/test windows
- Optimises parameters on training set
- Tests on held-out (OOS) data
- Reports OOS metrics for each window

**Why it matters:** In-sample performance is meaningless. Only OOS performance counts.

**Decision gate:** Positive Sharpe in > 60% of OOS windows.

---

## Stage 5 — Monte Carlo Robustness

**Command:** `./launch.sh monte-carlo`

**What it does:**
- **Bootstrap:** Reshuffles trade order 1000× to test path-dependency
- **Noise injection:** Adds random noise to trade PnLs to test fragility
- Reports confidence intervals for Sharpe, return, max drawdown
- Computes risk of ruin at 25%, 50%, 75% loss thresholds
- Computes p-values (probability of random trades beating strategy)

**Decision gate:** p-value < 0.05, risk of ruin (50%) < 5%.

---

## Stage 6 — Simulation

**Command:** `./launch.sh simulate`

**What it does:**
- Full end-to-end pipeline with synthetic or stored data
- Tests the complete system: feeds → classifier → signals → confirmation → portfolio → risk
- No external connectivity required
- Produces full performance report

**Decision gate:** System runs without errors, metrics consistent with backtest.

---

## Stage 7 — Paper Trading

**Command:** `./launch.sh paper`

**What it does:**
- Connects to exchange testnet/sandbox
- Runs live event-driven pipeline
- Submits simulated orders
- Tracks real-time performance

**Safety controls:**
- `dry_run: true` by default
- `require_sandbox: true` by default
- Kill switch available

**Decision gate:** Consistent positive PnL over 2+ weeks before considering live.

---

## Core Principles

| Principle | How We Enforce It |
|---|---|
| No look-ahead bias | Events processed chronologically; signals use only past data |
| No survivorship bias | AssetUniverse tracks delisted assets |
| Realistic costs | Commission + slippage + spread modeled |
| Walk-forward validation | Rolling OOS windows |
| Out-of-sample testing | Train/test split enforced |
| Risk-first architecture | Kill switch, drawdown breaker, daily loss limit |
| Full reproducibility | Seed-based RNG, config snapshots, experiment tracking |

---

## Experiment Tracking

Every run automatically records:
- Timestamp
- Full config snapshot
- Git commit hash
- All performance metrics
- Equity curve
- Trade log

Results saved to `results/run_{experiment_id}/` with JSON files.
