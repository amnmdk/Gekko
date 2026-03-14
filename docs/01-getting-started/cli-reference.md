# CLI Reference

ndbot provides 10 commands accessible via the `ndbot` CLI entry point.

---

## `ndbot simulate`

Run a simulation with synthetic data. No external APIs required.

```bash
ndbot simulate --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--events` | `40` | Number of synthetic events per domain |
| `--candles` | `500` | Number of synthetic candles |
| `--seed` | `42` | Random seed for reproducibility |
| `--log-level` | `INFO` | Log verbosity (DEBUG, INFO, WARNING, ERROR) |

**Output**: Performance table with equity, return %, Sharpe, trades, max drawdown.

---

## `ndbot backtest`

Replay stored events and candles in backtest mode.

```bash
ndbot backtest --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--events-file` | `None` | JSON file of stored events |
| `--candles-file` | `None` | CSV file of OHLCV candles |
| `--seed` | `42` | Random seed (used if no data files) |
| `--log-level` | `INFO` | Log verbosity |

If no files are provided, falls back to synthetic data.

**Candle CSV format**: Index column must be UTC timestamps. Columns: `open`, `high`, `low`, `close`, `volume`.

---

## `ndbot event-study`

Run an event study analysis — measure price impact at multiple horizons.

```bash
ndbot event-study --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--output-dir` | `results` | Directory for output files |
| `--n-events` | `30` | Synthetic events if no stored events |
| `--seed` | `42` | Random seed |
| `--log-level` | `INFO` | Log verbosity |

**Output**: Aggregate statistics per horizon (5m, 15m, 1h, 4h), PNG chart saved to output directory.

---

## `ndbot walkforward`

Run walk-forward out-of-sample validation.

```bash
ndbot walkforward --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--output-dir` | `results` | Directory for output files |
| `--n-events` | `200` | Events to generate across history |
| `--seed` | `42` | Random seed |
| `--log-level` | `INFO` | Log verbosity |

**Output**: Table of OOS Sharpe, return %, max drawdown per window. Results saved to database.

---

## `ndbot grid`

Parameter grid search over confidence and risk thresholds.

```bash
ndbot grid --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--output-dir` | `results` | Directory for output files |
| `--n-events` | `100` | Events to generate |
| `--seed` | `42` | Random seed |
| `--log-level` | `INFO` | Log verbosity |

**Search space**:
- `min_confidence`: [0.30, 0.40, 0.50, 0.60, 0.70]
- `risk_per_trade`: [0.005, 0.01, 0.015, 0.02, 0.03]

**Output**: Colour-coded table of all parameter combinations. Best combo highlighted.

---

## `ndbot paper`

Run paper trading against an exchange testnet/sandbox.

```bash
ndbot paper --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--duration` | `None` | Run duration in seconds (None = indefinite) |
| `--log-level` | `INFO` | Log verbosity |

**Safety**: DRY_RUN=true by default. Sandbox required. See [[../08-risk-safety/paper-trading|Paper Trading Safety]].

---

## `ndbot status`

Show recent runs and system status.

```bash
ndbot status [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--db` | `data/ndbot.db` | Path to SQLite database |
| `--limit` | `10` | Number of recent runs to show |

**Output**: Table of Run ID, Name, Mode, Start Time, Trades, PnL, Sharpe.

---

## `ndbot seed-demo`

Generate demo data and run the full pipeline end-to-end. No config file required.

```bash
ndbot seed-demo [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--output-dir` | `results` | Directory for output files |
| `--seed` | `1337` | Random seed |

---

## `ndbot export`

Export events and/or trades for a run to CSV or JSON.

```bash
ndbot export --run-id <id> [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--run-id` | *required* | Run ID (from `ndbot status`) |
| `--format` | `csv` | Output format: `csv` or `json` |
| `--output-dir` | `results` | Directory for output files |
| `--db` | `data/ndbot.db` | Path to SQLite database |
| `--what` | `both` | What to export: `trades`, `events`, or `both` |

---

## `ndbot validate-config`

Validate a config file and print a health-check report.

```bash
ndbot validate-config --config config/sample.yaml [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config, -c` | *required* | Path to YAML config file |
| `--check-feeds` | `false` | Test HTTP connectivity to feed URLs |

**Output**: Colour-coded table showing each config parameter with OK/WARN status. Warnings for aggressive risk settings.
