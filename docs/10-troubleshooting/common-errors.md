# Common Errors

## Configuration Errors

### `ValidationError: mode must be one of {'simulate', 'backtest', 'paper'}`

**Cause**: Invalid `mode` in config file.
**Fix**: Set mode to exactly `simulate`, `backtest`, or `paper`.

### `ValidationError: initial_capital ≥ 1.0`

**Cause**: Capital set below $1.
**Fix**: Set `portfolio.initial_capital` to at least 1.0.

### `ValidationError: risk_per_trade ≤ 0.1`

**Cause**: Risk per trade exceeds 10%.
**Fix**: Set `signals[].risk_per_trade` to 0.1 or less.

### `Config not found: path/to/config.yaml`

**Cause**: Config file doesn't exist at the specified path.
**Fix**: Check path. Use `config/sample.yaml` as starting point.

---

## Paper Trading Errors

### `SAFETY BLOCK: Cannot run paper mode with dry_run=false and sandbox=false`

**Cause**: Both safety guards are disabled.
**Fix**: Set `paper.require_sandbox: true`. This is the intended behaviour — live trading is deliberately blocked.

### `Exchange sandbox mode not available`

**Cause**: The specified exchange doesn't support sandbox/testnet.
**Fix**: Use an exchange with testnet: Binance, Bybit, OKX.

### `AuthenticationError`

**Cause**: Invalid or expired API keys.
**Fix**: Generate new testnet API keys and update environment variables.

---

## Feed Errors

### `Feed reuters-commodities returned HTTP 403`

**Cause**: Feed URL requires different headers or is geo-blocked.
**Fix**: Check if the feed is accessible from your location. Try a different feed URL.

### `Feed X timed out after 3 attempts`

**Cause**: Network connectivity issue or feed server is down.
**Fix**: Check internet connection. The system will retry automatically on next poll cycle.

### `Feed X rate-limited (HTTP 429)`

**Cause**: Polling too frequently.
**Fix**: Increase `poll_interval_seconds` for that feed.

---

## Database Errors

### `sqlite3.OperationalError: database is locked`

**Cause**: Multiple processes accessing the same database file.
**Fix**: Stop other ndbot processes. Use different `db_path` for concurrent runs.

### `Database not found: data/ndbot.db`

**Cause**: First run or database was deleted.
**Fix**: Run `ndbot seed-demo` or `ndbot simulate` to create the database.

---

## Test Errors

### `ModuleNotFoundError: No module named 'httpx'`

**Cause**: Dev dependencies not installed.
**Fix**: `pip install -e ".[dev]"`

### `profit_factor is infinite`

**Not an error**. When all trades are winners (gross_loss = 0), profit factor is mathematically infinite. This is valid.

### `test_walkforward_smoke` returns error dict

**Not a failure**. Walk-forward with very short candle ranges may not form valid windows. The test accepts either `n_windows` or `error` in the result.

---

## Docker Errors

### `Backend service unhealthy`

**Cause**: Backend container not starting properly.
**Fix**: Check logs: `docker compose logs backend`. Common issues: port conflict, missing config.

### `QEMU: unhandled CPU exception`

**Cause**: ARM64 emulation issues on x86 host.
**Fix**: Install QEMU: `docker run --privileged --rm tonistiigi/binfmt --install all`

### `Permission denied` on volumes

**Cause**: Docker volume permissions don't match host user.
**Fix**: `chmod 777 data/ logs/ results/` or adjust Docker user.

---

## Performance Issues

### Simulation is slow

**Causes and fixes**:
- Too many candles: Reduce `--candles` parameter
- Walk-forward with >50k candles: Use `--n-events` to limit
- matplotlib rendering: Use `--log-level WARNING` to reduce output
- Pi 5 thermal throttling: Ensure adequate cooling

### High memory usage

**Causes and fixes**:
- Large `candle_window`: Reduce to 200-300
- Walk-forward generating huge histories: Cap at 50k candles
- Multiple concurrent processes: Use one process at a time on Pi 5
