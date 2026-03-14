# Paper Trading Safety

Step-by-step guide to safely enabling paper trading on exchange testnets.

---

## Prerequisites

1. A CCXT-compatible exchange with testnet support
2. Testnet API key and secret
3. A validated ndbot config file

---

## Step 1: Start in DRY_RUN Mode

This is the default. Orders are logged but never submitted.

```yaml
paper:
  exchange_id: "binance"
  dry_run: true           # DEFAULT — no real orders
  require_sandbox: true
```

```bash
ndbot paper --config config/paper.yaml --duration 300
```

Monitor the logs for 5 minutes. Check that:
- Feeds are polling successfully
- Events are being classified
- Signals are being generated (or rejected with reasons)
- No unexpected errors

---

## Step 2: Get Testnet Credentials

### Binance Testnet

1. Go to https://testnet.binance.vision/
2. Log in with GitHub
3. Generate API keys
4. Note: Testnet funds are free and unlimited

### Bybit Testnet

1. Go to https://testnet.bybit.com/
2. Create account
3. Generate API keys

---

## Step 3: Set Credentials via Environment

**Never put API keys in YAML config files.**

```bash
export NDBOT__PAPER__API_KEY=your_testnet_key
export NDBOT__PAPER__API_SECRET=your_testnet_secret
```

Or create a `.env` file (gitignored):

```bash
# .env
NDBOT__PAPER__API_KEY=your_testnet_key
NDBOT__PAPER__API_SECRET=your_testnet_secret
```

---

## Step 4: Enable Testnet Orders

Update your config:

```yaml
paper:
  exchange_id: "binance"
  dry_run: false          # Enable order submission
  require_sandbox: true   # KEEP THIS TRUE
```

```bash
ndbot paper --config config/paper.yaml --duration 60
```

Check logs for:
- `Exchange sandbox mode enabled.`
- Order submission messages
- No `SAFETY BLOCK` errors

---

## Step 5: Monitor and Validate

```bash
# Check runs
ndbot status

# Export trades
ndbot export --run-id <id> --what trades --format csv

# Watch logs
tail -f logs/ndbot.log
```

---

## What Can Go Wrong

| Scenario | What Happens | Fix |
|---|---|---|
| Wrong API key | CCXT authentication error | Check key/secret pair |
| Exchange has no sandbox | `RuntimeError: sandbox not available` | Use a supported exchange |
| Both dry_run=false and sandbox=false | `RuntimeError` raised | Set `require_sandbox: true` |
| Network timeout | Feed retry with backoff; CCXT retry | Check internet connectivity |
| Rate limit hit | HTTP 429, exponential backoff | Increase `poll_interval_seconds` |

---

## Safety Guarantees

1. **Default state is safe**: `dry_run=true, require_sandbox=true` — zero risk
2. **Two changes required**: Must set BOTH `dry_run=false` AND provide API keys
3. **Live trading blocked**: `dry_run=false + require_sandbox=false` → RuntimeError
4. **Testnet money only**: With `require_sandbox=true`, only testnet funds at risk
5. **Full audit trail**: Every order is logged regardless of dry_run state
6. **Circuit breakers active**: Daily loss + drawdown limits work in paper mode too

---

## Transitioning to Longer Runs

After validating with short durations:

```bash
# 1 hour test
ndbot paper --config config/paper.yaml --duration 3600

# 8 hour test
ndbot paper --config config/paper.yaml --duration 28800

# Indefinite (use Ctrl+C to stop, or systemd)
ndbot paper --config config/paper.yaml
```

Use `ndbot status` and `ndbot export` to review results after each test period.
