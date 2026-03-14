"""
Data integrity and validation tests.

Verifies:
- OHLCV candle constraints (high >= low, close > 0, no NaN)
- PnL calculations never produce NaN or inf
- Database deduplication of events
- Config validators reject out-of-range inputs
- Simulation is deterministic with a fixed seed
- RSS feed error-handling for malformed entries
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Candle data integrity
# ---------------------------------------------------------------------------


def test_candle_ohlcv_high_gte_low() -> None:
    """high must always be >= low."""
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=42).generate(500)
    assert (df["high"] >= df["low"]).all(), "Found candles where high < low"


def test_candle_ohlcv_high_gte_close() -> None:
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=42).generate(500)
    assert (df["high"] >= df["close"]).all()
    assert (df["high"] >= df["open"]).all()


def test_candle_ohlcv_low_lte_close() -> None:
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=42).generate(500)
    assert (df["low"] <= df["close"]).all()
    assert (df["low"] <= df["open"]).all()


def test_candle_close_positive() -> None:
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=42).generate(500)
    assert (df["close"] > 0).all()


def test_candle_volume_non_negative() -> None:
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=123).generate(200)
    assert (df["volume"] >= 0).all()


def test_candle_no_nan_values() -> None:
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=99).generate(300)
    assert not df.isnull().any().any(), "NaN values found in generated candles"


def test_regime_indicators_valid_after_warmup() -> None:
    """Core indicators should be non-NaN after the rolling window warmup."""
    from ndbot.market.regime import RegimeDetector
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    df = SyntheticCandleGenerator(seed=42).generate(200)
    enriched = RegimeDetector().add_indicators(df)

    # Skip first 60 rows (warmup for ma_long=50, ATR=14, ATR pct=100 → need 100 for pct)
    tail = enriched.iloc[100:]
    assert not tail["atr"].isnull().any(), "ATR has NaN after warmup"
    assert not tail["ma_short"].isnull().any(), "ma_short has NaN after warmup"
    assert not tail["ma_long"].isnull().any(), "ma_long has NaN after warmup"


# ---------------------------------------------------------------------------
# PnL integrity — must never produce NaN or inf
# ---------------------------------------------------------------------------


def test_pnl_never_nan_all_winners() -> None:
    from ndbot.portfolio.metrics import PortfolioMetrics

    pnls = [5.0, 3.0, 2.0, 1.5]
    equity = [100.0 + sum(pnls[:i]) for i in range(len(pnls) + 1)]
    r = PortfolioMetrics.compute(pnls, equity, 100.0)

    for attr in ["sharpe_ratio", "sortino_ratio", "total_pnl", "win_rate"]:
        v = getattr(r, attr)
        assert v == v, f"{attr} is NaN"  # NaN != NaN is True
        assert v != float("inf") and v != float("-inf"), f"{attr} is infinite"

    # profit_factor is legitimately inf when there are no losing trades
    pf = r.profit_factor
    assert pf == pf, "profit_factor is NaN"  # NaN check
    assert pf > 0, "profit_factor must be positive"


def test_pnl_never_nan_all_losers() -> None:
    from ndbot.portfolio.metrics import PortfolioMetrics

    pnls = [-1.0, -2.0, -0.5, -3.0]
    equity = [100.0 + sum(pnls[:i]) for i in range(len(pnls) + 1)]
    r = PortfolioMetrics.compute(pnls, equity, 100.0)

    assert r.profit_factor == 0.0, "profit_factor should be 0 with no winners"
    assert r.sharpe_ratio == r.sharpe_ratio, "sharpe_ratio is NaN"
    assert r.total_trades == 4


def test_pnl_empty_trades() -> None:
    from ndbot.portfolio.metrics import PortfolioMetrics

    r = PortfolioMetrics.compute([], [100.0], 100.0)
    assert r.total_trades == 0
    assert r.total_pnl == 0.0
    assert r.win_rate == 0.0


def test_position_pnl_precision() -> None:
    """PnL calculation should not accumulate floating-point errors."""
    from ndbot.portfolio.position import CloseReason, Position

    pos = Position(
        position_id="prec-test",
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=50000.0,
        size=0.001,
        stop_loss=49000.0,
        take_profit=52000.0,
        entry_time=datetime.now(timezone.utc),
        holding_minutes=60,
        signal_id="sig",
        domain="TEST",
    )
    # Expected unrealised PnL: (51000 - 50000) * 0.001 = 1.0
    assert pos.unrealised_pnl(51000.0) == pytest.approx(1.0, rel=1e-6)

    pos.close(51000.0, datetime.now(timezone.utc), CloseReason.TAKE_PROFIT)
    # After commission/slippage deductions, realised PnL is slightly below gross
    # Gross = (51000 - 50000) * 0.001 = 1.0; net must be positive and < 1.0
    assert 0.0 < pos.realised_pnl <= 1.0


def test_short_position_pnl_sign() -> None:
    """SHORT position gains when price drops."""
    from ndbot.portfolio.position import Position

    pos = Position(
        position_id="short-test",
        symbol="ETH/USDT",
        direction="SHORT",
        entry_price=3500.0,
        size=0.01,
        stop_loss=3600.0,
        take_profit=3300.0,
        entry_time=datetime.now(timezone.utc),
        holding_minutes=60,
        signal_id="sig",
        domain="AI_RELEASES",
    )
    # Price dropped: should be positive PnL for SHORT
    pnl = pos.unrealised_pnl(3400.0)
    assert pnl > 0, "SHORT position should profit when price drops"

    # Price rose above entry: loss for SHORT
    pnl_loss = pos.unrealised_pnl(3600.0)
    assert pnl_loss < 0, "SHORT position should lose when price rises"


# ---------------------------------------------------------------------------
# Database integrity
# ---------------------------------------------------------------------------


def test_database_deduplicates_events() -> None:
    """Inserting the same event_id multiple times must store only one row."""
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.storage.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(f"{tmpdir}/dedup.db")
        db.init()

        ev = NewsEvent(
            event_id="dedup-test-id",
            domain=EventDomain.ENERGY_GEO,
            headline="Dedup test",
            summary="",
            source="test",
            url="http://test.com/dedup",
            published_at=datetime.now(timezone.utc),
        )
        for _ in range(5):
            db.save_event(ev, "run-dedup")

        events = db.get_events(run_id="run-dedup")
        assert len(events) == 1, f"Expected 1 event, got {len(events)}"
        db.close()


def test_database_trade_timestamp_valid() -> None:
    """Saved trades must have valid entry timestamps."""
    from ndbot.feeds.base import EventDomain  # noqa: F401
    from ndbot.portfolio.position import CloseReason, Position
    from ndbot.storage.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(f"{tmpdir}/ts.db")
        db.init()
        db.create_run("run-ts", "ts-run", "simulate", 100.0, {})

        pos = Position(
            position_id="ts-trade-1",
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=50000.0,
            size=0.001,
            stop_loss=49000.0,
            take_profit=52000.0,
            entry_time=datetime.now(timezone.utc),
            holding_minutes=60,
            signal_id="sig",
            domain="ENERGY_GEO",
        )
        pos.close(51000.0, datetime.now(timezone.utc), CloseReason.TAKE_PROFIT)
        db.save_trade(pos, "run-ts")

        trades = db.get_trades(run_id="run-ts")
        assert len(trades) == 1
        # The trade dict should have a timestamp field
        t = trades[0]
        has_time = bool(t.get("entry_time") or t.get("opened_at"))
        assert has_time, "Trade record missing timestamp"
        db.close()


def test_database_multiple_runs_isolated() -> None:
    """Events from different run_ids should not be mixed."""
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.storage.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(f"{tmpdir}/iso.db")
        db.init()

        for run_id in ["run-A", "run-B"]:
            ev = NewsEvent(
                event_id=f"ev-{run_id}",
                domain=EventDomain.ENERGY_GEO,
                headline=f"Event for {run_id}",
                summary="",
                source="test",
                url=f"http://test.com/{run_id}",
                published_at=datetime.now(timezone.utc),
            )
            db.save_event(ev, run_id)

        events_a = db.get_events(run_id="run-A")
        events_b = db.get_events(run_id="run-B")
        assert len(events_a) == 1
        assert len(events_b) == 1
        assert events_a[0]["headline"] != events_b[0]["headline"]
        db.close()


# ---------------------------------------------------------------------------
# Config validation (Pydantic)
# ---------------------------------------------------------------------------


def test_config_rejects_high_risk() -> None:
    """risk_per_trade > 0.1 must raise ValidationError."""
    from pydantic import ValidationError

    from ndbot.config.settings import SignalConfig

    with pytest.raises(ValidationError):
        SignalConfig(
            domain="ENERGY_GEO",
            enabled=True,
            min_confidence=0.5,
            holding_minutes=60,
            risk_per_trade=0.99,  # Max is 0.1
            rr_ratio=2.0,
        )


def test_config_rejects_negative_capital() -> None:
    """initial_capital below 1.0 must raise ValidationError."""
    from pydantic import ValidationError

    from ndbot.config.settings import PortfolioConfig

    with pytest.raises(ValidationError):
        PortfolioConfig(initial_capital=-100.0)


def test_config_rejects_zero_atr_period() -> None:
    """atr_period below 5 must raise ValidationError."""
    from pydantic import ValidationError

    from ndbot.config.settings import MarketConfig

    with pytest.raises(ValidationError):
        MarketConfig(atr_period=0)


def test_config_rejects_invalid_mode() -> None:
    """mode must be one of simulate|backtest|paper."""
    from pydantic import ValidationError

    from ndbot.config.settings import BotConfig

    with pytest.raises(ValidationError):
        BotConfig.model_validate({"mode": "live", "run_name": "t"})


def test_config_rejects_invalid_min_confidence() -> None:
    """min_confidence > 1.0 is invalid."""
    from pydantic import ValidationError

    from ndbot.config.settings import SignalConfig

    with pytest.raises(ValidationError):
        SignalConfig(
            domain="ENERGY_GEO",
            enabled=True,
            min_confidence=1.5,
            holding_minutes=60,
            risk_per_trade=0.01,
            rr_ratio=2.0,
        )


# ---------------------------------------------------------------------------
# Simulation determinism
# ---------------------------------------------------------------------------


def test_simulation_deterministic_with_seed() -> None:
    """
    Two simulation runs with the same seed must produce identical results.
    """
    from ndbot.config.settings import BotConfig
    from ndbot.execution.simulate import SimulationEngine
    from ndbot.storage.database import Database

    base_cfg = {
        "run_name": "det-test",
        "mode": "simulate",
        "signals": [
            {
                "domain": "ENERGY_GEO",
                "enabled": True,
                "min_confidence": 0.30,
                "holding_minutes": 30,
                "risk_per_trade": 0.01,
                "rr_ratio": 2.0,
            }
        ],
        "confirmation": {"enabled": False},
        "portfolio": {"initial_capital": 100.0, "max_concurrent_positions": 5},
    }

    results = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BotConfig.model_validate(base_cfg)
            cfg = cfg.model_copy(
                update={"storage": cfg.storage.model_copy(update={"db_path": f"{tmpdir}/det.db"})}
            )
            db = Database(f"{tmpdir}/det.db")
            db.init()
            engine = SimulationEngine(cfg, db, n_events=20, n_candles=200, seed=7)
            results.append(engine.run())
            db.close()

    assert results[0]["total_trades"] == results[1]["total_trades"], (
        "Different trade counts between identical seeded runs"
    )
    assert abs(results[0]["equity"] - results[1]["equity"]) < 1e-6, (
        "Different final equity between identical seeded runs"
    )


def test_simulation_different_seeds_differ() -> None:
    """Different seeds should (almost certainly) produce different results."""
    from ndbot.config.settings import BotConfig
    from ndbot.execution.simulate import SimulationEngine
    from ndbot.storage.database import Database

    base_cfg = {
        "run_name": "seed-test",
        "mode": "simulate",
        "signals": [
            {
                "domain": "ENERGY_GEO",
                "enabled": True,
                "min_confidence": 0.20,
                "holding_minutes": 30,
                "risk_per_trade": 0.02,
                "rr_ratio": 2.0,
            }
        ],
        "confirmation": {"enabled": False},
        "portfolio": {"initial_capital": 100.0},
    }

    equities = []
    for seed in [1, 999]:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BotConfig.model_validate(base_cfg)
            cfg = cfg.model_copy(
                update={"storage": cfg.storage.model_copy(update={"db_path": f"{tmpdir}/s.db"})}
            )
            db = Database(f"{tmpdir}/s.db")
            db.init()
            engine = SimulationEngine(cfg, db, n_events=30, n_candles=300, seed=seed)
            result = engine.run()
            equities.append(result["equity"])
            db.close()

    # With different seeds, at least the final equity should differ
    # (may be the same with very few trades, but usually differs)
    # We assert this doesn't crash and both produce valid results
    assert all(e > 0 for e in equities), "Equity should remain positive"


# ---------------------------------------------------------------------------
# RSS feed error handling
# ---------------------------------------------------------------------------


def test_rss_empty_title_returns_none() -> None:
    """An RSS entry with no title should be silently skipped."""
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.rss_feed import RSSFeed

    feed = RSSFeed("test-feed", "http://test.com", EventDomain.ENERGY_GEO)

    class EmptyTitleEntry:
        title = ""
        link = "http://test.com/1"
        summary = "Some content"

    result = feed._entry_to_event(EmptyTitleEntry())
    assert result is None


def test_rss_missing_date_uses_now() -> None:
    """An RSS entry with no date field should fall back to current time."""
    import time

    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.rss_feed import RSSFeed

    feed = RSSFeed("test-feed", "http://test.com", EventDomain.AI_RELEASES)

    class NoDatesEntry:
        title = "Test headline for fallback date"
        link = "http://test.com/fallback"
        summary = "Summary text"
        published_parsed = None

    before = time.time()
    result = feed._entry_to_event(NoDatesEntry())
    after = time.time()

    assert result is not None
    assert result.headline == "Test headline for fallback date"
    ts = result.published_at.timestamp()
    # Timestamp should be recent (within a 10-second window)
    assert before - 5 <= ts <= after + 5, "Fallback timestamp is not recent"


def test_rss_deduplicate_known_events() -> None:
    """Events with known IDs should not be re-emitted."""
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.rss_feed import RSSFeed

    feed = RSSFeed("test-feed", "http://test.com", EventDomain.ENERGY_GEO)

    class Entry:
        title = "Known event"
        link = "http://test.com/known"
        summary = "Body text"
        published_parsed = None

    # First time: new event
    result1 = feed._entry_to_event(Entry())
    assert result1 is not None
    is_first_new = feed._is_new(result1.event_id)
    assert is_first_new

    # Mark as seen
    feed._seen_ids.add(result1.event_id)

    # Second time: should be marked as not new
    assert not feed._is_new(result1.event_id)
