# Test Suite

87 tests across 4 modules. All pass in ~4 seconds.

```bash
pytest tests/ -v
```

---

## Test Files

### `test_basic.py` — 21 Tests

Core pipeline and integration smoke tests.

| Test | Verifies |
|---|---|
| `test_config_loads` | BotConfig can be instantiated with defaults |
| `test_config_yaml_roundtrip` | Config survives YAML save → load cycle |
| `test_synthetic_feed_generates_events` | SyntheticFeed produces non-empty event batches |
| `test_synthetic_feed_ai_domain` | AI_RELEASES domain events have correct domain |
| `test_news_event_id_deterministic` | Same inputs produce same event_id hash |
| `test_keyword_classifier_energy_geo` | Energy keywords correctly classify domain |
| `test_keyword_classifier_ai_releases` | AI keywords correctly classify domain |
| `test_entity_extractor` | Extracts known ORGs and LOCATIONs |
| `test_synthetic_candle_generator` | Candles have correct columns and shape |
| `test_regime_detector` | Regime detection runs without error |
| `test_confidence_model_score` | Confidence score is in [0, 1] |
| `test_risk_sizing` | Risk engine computes valid sizing |
| `test_position_pnl` | Position close calculates PnL correctly |
| `test_portfolio_metrics` | PerformanceReport computes all fields |
| `test_database_events` | Events save and retrieve from SQLite |
| `test_simulate_smoke` | Full simulation runs end-to-end |
| `test_backtest_smoke` | Backtest with external data runs |
| `test_walkforward_smoke` | Walk-forward validation runs |
| `test_event_study_smoke` | Event study analysis runs |

### `test_api.py` — 26 Tests

FastAPI REST API and WebSocket integration tests.

| Test | Verifies |
|---|---|
| `test_api_health` | `GET /api/health` returns 200 |
| `test_api_status` | `GET /api/status` returns summary dict |
| `test_api_balance` | Balance endpoint has required fields |
| `test_api_events_returns_list` | Events endpoint returns array |
| `test_api_events_limit_query` | Limit parameter works |
| `test_api_events_limit_invalid` | Invalid limit returns 422 |
| `test_api_positions_returns_list` | Positions returns array |
| `test_api_trades_returns_list` | Trades returns array |
| `test_api_trades_limit_query` | Trade limit parameter works |
| `test_api_prices_structure` | Prices returns dict |
| `test_api_equity_curve_structure` | Equity curve returns array |
| `test_api_equity_curve_limit` | Equity curve limit works |
| `test_api_metrics_returns_dict` | Metrics endpoint returns dict |
| `test_api_config_patch_*` | Config PATCH for all fields |
| `test_api_reset_*` | Reset with custom/default capital, clears trades, rejects <10 |
| `test_api_websocket_snapshot` | WebSocket sends snapshot on connect |

### `test_signals.py` — 17 Tests

Signal generation, confidence model, and NER.

| Test | Verifies |
|---|---|
| `test_energy_geo_bearish_yields_short` | Bearish energy event → SHORT signal |
| `test_energy_geo_bullish_yields_long` | Bullish energy event → LONG signal |
| `test_energy_geo_below_threshold_returns_none` | Low confidence → no signal |
| `test_energy_geo_wrong_domain_returns_none` | Wrong domain → no signal |
| `test_energy_geo_signal_has_risk_fields` | Signal includes SL, TP, risk |
| `test_ai_releases_launch_yields_long` | AI launch → LONG signal |
| `test_ai_releases_incident_yields_short` | AI incident → SHORT signal |
| `test_ai_releases_below_threshold_returns_none` | Low confidence → no signal |
| `test_confidence_model_always_in_range` | Score always in [0, 1] |
| `test_confidence_model_higher_importance_higher_score` | Higher importance → higher score |
| `test_classifier_*` | Domain detection and no-crash on unknown |
| `test_entity_extractor_*` | Finds ORGs, LOCATIONs, handles edge cases |

### `test_validation.py` — 22 Tests

Data integrity, config validation, and determinism.

| Test | Verifies |
|---|---|
| `test_candle_ohlcv_*` | OHLCV invariants: high≥low, close>0, no NaN |
| `test_regime_indicators_valid_after_warmup` | ATR, MAs non-NaN after warmup |
| `test_pnl_never_nan_*` | PnL is never NaN (all winners, all losers, empty) |
| `test_position_pnl_precision` | Net PnL after commission is correct |
| `test_short_position_pnl_sign` | Short positions have correct PnL sign |
| `test_database_deduplicates_events` | 5 identical events → 1 stored |
| `test_database_trade_timestamp_valid` | Trade timestamps are valid |
| `test_database_multiple_runs_isolated` | Runs don't interfere with each other |
| `test_config_rejects_*` | Invalid configs are rejected (high risk, negative capital, etc.) |
| `test_simulation_deterministic_with_seed` | Same seed → identical results |
| `test_simulation_different_seeds_differ` | Different seeds → different results |
| `test_rss_*` | Empty title → None, missing date → fallback, dedup via seen_ids |

---

## Key Invariants

These are the guarantees that the test suite enforces:

1. **Confidence scores are always [0.05, 0.95]** for any input
2. **Simulation with same seed is byte-identical** (trades, equity)
3. **OHLCV candles are always valid**: high ≥ max(O,C), low ≤ min(O,C), close > 0
4. **Database deduplicates events** by event_id
5. **Below-threshold signals return None** (no ghost signals)
6. **Config validation rejects dangerous values** at load time
7. **All REST endpoints return 2xx** for valid requests
8. **WebSocket sends snapshot** immediately on connect
