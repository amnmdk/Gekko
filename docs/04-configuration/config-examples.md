# Configuration Examples

## Conservative Research Setup

Low risk, high confidence threshold. Fewer trades, lower drawdown.

```yaml
run_name: "conservative-research"
mode: simulate

market:
  symbol: "BTC/USDT"
  timeframe: "5m"

signals:
  - domain: ENERGY_GEO
    min_confidence: 0.65
    risk_per_trade: 0.005
    rr_ratio: 3.0
    holding_minutes: 120

  - domain: AI_RELEASES
    min_confidence: 0.65
    risk_per_trade: 0.005
    rr_ratio: 3.0
    holding_minutes: 90

portfolio:
  initial_capital: 1000.0
  max_concurrent_positions: 2
  max_daily_loss_pct: 0.03
  max_drawdown_pct: 0.10

confirmation:
  enabled: true
  breakout_threshold: 0.003
  volume_spike_multiplier: 2.0
```

---

## Aggressive Research Setup

Higher risk, lower threshold. More trades, higher potential drawdown.

```yaml
run_name: "aggressive-research"
mode: simulate

signals:
  - domain: ENERGY_GEO
    min_confidence: 0.30
    risk_per_trade: 0.03
    rr_ratio: 1.5
    holding_minutes: 45

  - domain: AI_RELEASES
    min_confidence: 0.30
    risk_per_trade: 0.03
    rr_ratio: 1.5
    holding_minutes: 30

portfolio:
  initial_capital: 500.0
  max_concurrent_positions: 5
  max_daily_loss_pct: 0.08
  max_drawdown_pct: 0.25

confirmation:
  enabled: false   # Skip confirmation for max signal capture
```

---

## Paper Trading (Binance Testnet)

```yaml
run_name: "paper-test"
mode: paper

feeds:
  - name: "reuters-commodities"
    url: "https://feeds.reuters.com/reuters/commoditiesNews"
    domain: ENERGY_GEO
    poll_interval_seconds: 60
    credibility_weight: 1.8
    enabled: true

  - name: "techcrunch-ai"
    url: "https://techcrunch.com/feed/"
    domain: AI_RELEASES
    poll_interval_seconds: 120
    credibility_weight: 1.5
    enabled: true

signals:
  - domain: ENERGY_GEO
    min_confidence: 0.50
    risk_per_trade: 0.01

  - domain: AI_RELEASES
    min_confidence: 0.50
    risk_per_trade: 0.01

paper:
  exchange_id: "binance"
  dry_run: true            # Start with dry run!
  require_sandbox: true
  # Set API keys via environment:
  # export NDBOT__PAPER__API_KEY=your_key
  # export NDBOT__PAPER__API_SECRET=your_secret
```

---

## Energy-Only Research

Focus only on geopolitical energy events.

```yaml
run_name: "energy-only"
mode: simulate

feeds:
  - name: "reuters-commodities"
    url: "https://feeds.reuters.com/reuters/commoditiesNews"
    domain: ENERGY_GEO
    credibility_weight: 1.8
    enabled: true

  - name: "oilprice"
    url: "https://oilprice.com/rss/main"
    domain: ENERGY_GEO
    credibility_weight: 1.2
    enabled: true

signals:
  - domain: ENERGY_GEO
    enabled: true
    min_confidence: 0.45

  - domain: AI_RELEASES
    enabled: false           # Disable AI signals
```

---

## Walk-Forward Validation Config

Optimised for research with shorter windows for faster iteration.

```yaml
run_name: "wf-research"
mode: simulate

research:
  train_days: 365            # 1 year train (faster than default 3y)
  test_days: 90              # 3 months test
  step_days: 30              # Monthly roll

portfolio:
  initial_capital: 100.0
  commission_rate: 0.001
```

---

## Environment Variable Overrides

Any config field can be overridden via environment variables:

```bash
export NDBOT__PAPER__API_KEY=your_testnet_key
export NDBOT__PAPER__API_SECRET=your_testnet_secret
export NDBOT__PAPER__DRY_RUN=true
```

Pattern: `NDBOT__SECTION__KEY=value` (double underscore separator)
