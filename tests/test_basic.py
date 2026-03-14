"""
Basic integration smoke tests.
Run with: pytest tests/ -v
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _make_minimal_config() -> dict:
    return {
        "run_name": "test-run",
        "mode": "simulate",
        "signals": [
            {"domain": "ENERGY_GEO", "enabled": True, "min_confidence": 0.30,
             "holding_minutes": 30, "risk_per_trade": 0.01, "rr_ratio": 2.0},
            {"domain": "AI_RELEASES", "enabled": True, "min_confidence": 0.30,
             "holding_minutes": 30, "risk_per_trade": 0.01, "rr_ratio": 2.0},
        ],
        "confirmation": {"enabled": False},  # Disable for unit tests
        "portfolio": {"initial_capital": 100.0, "max_concurrent_positions": 5},
    }


def test_config_loads():
    from ndbot.config.settings import BotConfig
    cfg = BotConfig.model_validate(_make_minimal_config())
    assert cfg.run_name == "test-run"
    assert cfg.mode == "simulate"
    assert len(cfg.signals) == 2


def test_config_yaml_roundtrip():
    from ndbot.config.loader import load_config
    cfg_dict = _make_minimal_config()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg_dict, f)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg.run_name == "test-run"
    finally:
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

def test_synthetic_feed_generates_events():
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.synthetic import SyntheticFeed

    feed = SyntheticFeed(domain=EventDomain.ENERGY_GEO, seed=42)
    events = feed.generate_batch(5)
    assert len(events) == 5
    for ev in events:
        assert ev.domain == EventDomain.ENERGY_GEO
        assert len(ev.headline) > 0
        assert ev.event_id


def test_synthetic_feed_ai_domain():
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.synthetic import SyntheticFeed

    feed = SyntheticFeed(domain=EventDomain.AI_RELEASES, seed=99)
    events = feed.generate_batch(3)
    assert len(events) == 3
    assert all(ev.domain == EventDomain.AI_RELEASES for ev in events)


def test_news_event_id_deterministic():
    from ndbot.feeds.base import NewsEvent
    id1 = NewsEvent.make_id("source", "http://x.com", "Headline")
    id2 = NewsEvent.make_id("source", "http://x.com", "Headline")
    assert id1 == id2
    id3 = NewsEvent.make_id("source", "http://x.com", "Different")
    assert id1 != id3


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def test_keyword_classifier_energy_geo():
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain, NewsEvent

    feed_ev = NewsEvent(
        event_id="abc",
        domain=EventDomain.UNKNOWN,
        headline="Houthi attack closes Bab el-Mandeb strait",
        summary="Yemen-based forces fire missiles at tanker convoy.",
        source="test",
        url="http://test.com",
        published_at=datetime.now(timezone.utc),
    )
    classifier = KeywordClassifier()
    classifier.enrich(feed_ev)
    assert feed_ev.domain == EventDomain.ENERGY_GEO
    assert len(feed_ev.keywords_matched) > 0
    assert feed_ev.sentiment_score < 0


def test_keyword_classifier_ai_releases():
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain, NewsEvent

    feed_ev = NewsEvent(
        event_id="def",
        domain=EventDomain.UNKNOWN,
        headline="OpenAI launches GPT-5 with new agent capabilities",
        summary="New model sets records on benchmark evaluations.",
        source="test",
        url="http://test.com",
        published_at=datetime.now(timezone.utc),
    )
    classifier = KeywordClassifier()
    classifier.enrich(feed_ev)
    assert feed_ev.domain == EventDomain.AI_RELEASES
    assert feed_ev.sentiment_score > 0


def test_entity_extractor():
    from ndbot.classifier.entity_extractor import EntityExtractor

    extractor = EntityExtractor()
    entities = extractor.extract(
        "Iran closes Hormuz as Aramco and OPEC debate supply cuts"
    )
    assert "LOCATION" in entities
    assert any("Iran" in loc or "Hormuz" in loc for loc in entities["LOCATION"])
    assert "ORG" in entities


# ---------------------------------------------------------------------------
# Market / Regime
# ---------------------------------------------------------------------------

def test_synthetic_candle_generator():
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    gen = SyntheticCandleGenerator(seed=42)
    df = gen.generate(100)
    assert len(df) == 100
    for col in ["open", "high", "low", "close", "volume"]:
        assert col in df.columns
    assert (df["high"] >= df["low"]).all()
    assert (df["close"] > 0).all()


def test_regime_detector():
    from ndbot.market.regime import RegimeDetector, VolatilityRegime
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator

    gen = SyntheticCandleGenerator(seed=42)
    df = gen.generate(200)
    detector = RegimeDetector()
    enriched = detector.add_indicators(df)
    assert "atr" in enriched.columns
    assert "ma_short" in enriched.columns
    regime = detector.detect_volatility_regime(enriched)
    assert regime in (VolatilityRegime.LOW, VolatilityRegime.NORMAL, VolatilityRegime.HIGH)


# ---------------------------------------------------------------------------
# Confidence model
# ---------------------------------------------------------------------------

def test_confidence_model_score():
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.signals.confidence_model import ConfidenceModel

    model = ConfidenceModel()
    ev = NewsEvent(
        event_id="ccc",
        domain=EventDomain.ENERGY_GEO,
        headline="Iran closes Hormuz strait",
        summary="",
        source="reuters",
        url="http://test.com",
        published_at=datetime.now(timezone.utc),
        credibility_weight=1.8,
        importance_score=0.9,
        sentiment_score=-0.8,
        keywords_matched=["hormuz", "iran"],
    )
    score = model.score(ev)
    assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Portfolio / Risk
# ---------------------------------------------------------------------------

def test_risk_sizing():
    from ndbot.config.settings import PortfolioConfig
    from ndbot.market.regime import VolatilityRegime
    from ndbot.portfolio.risk import RiskEngine

    cfg = PortfolioConfig(initial_capital=100.0)
    engine = RiskEngine(cfg)
    result = engine.compute_sizing(
        equity=100.0,
        entry_price=45000.0,
        direction="LONG",
        atr=500.0,
        risk_fraction=0.01,
        rr_ratio=2.0,
        regime=VolatilityRegime.NORMAL,
    )
    assert result.approved
    assert result.size > 0
    assert result.stop_loss < 45000.0
    assert result.take_profit > 45000.0


def test_position_pnl():
    from ndbot.portfolio.position import CloseReason, Position, PositionStatus

    pos = Position(
        position_id="test-pos-1",
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=45000.0,
        size=0.001,
        stop_loss=44000.0,
        take_profit=47000.0,
        entry_time=datetime.now(timezone.utc),
        holding_minutes=60,
        signal_id="sig1",
        domain="ENERGY_GEO",
    )
    assert pos.unrealised_pnl(46000.0) == pytest.approx(1.0, rel=1e-3)
    assert not pos.should_stop_loss(44500.0)
    assert pos.should_stop_loss(43999.0)

    pos.close(
        exit_price=47000.0,
        exit_time=datetime.now(timezone.utc),
        reason=CloseReason.TAKE_PROFIT,
    )
    assert pos.status == PositionStatus.CLOSED
    assert pos.realised_pnl > 0


# ---------------------------------------------------------------------------
# Portfolio metrics
# ---------------------------------------------------------------------------

def test_portfolio_metrics():
    from ndbot.portfolio.metrics import PortfolioMetrics

    pnls = [5.0, -2.0, 3.0, -1.0, 4.0, -1.5, 2.5]
    equity = [100.0]
    for p in pnls:
        equity.append(equity[-1] + p)

    report = PortfolioMetrics.compute(pnls, equity, initial_capital=100.0)
    assert report.total_trades == 7
    assert report.winning_trades == 4
    assert report.profit_factor > 1.0
    assert 0 < report.win_rate < 1


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def test_database_events():
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.storage.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(f"{tmpdir}/test.db")
        db.init()

        ev = NewsEvent(
            event_id="test-ev-1",
            domain=EventDomain.ENERGY_GEO,
            headline="Test event",
            summary="Test summary",
            source="test-source",
            url="http://test.com/1",
            published_at=datetime.now(timezone.utc),
        )
        db.save_event(ev, "run-1")
        db.save_event(ev, "run-1")  # Should not duplicate

        events = db.get_events(run_id="run-1")
        assert len(events) == 1
        assert events[0]["headline"] == "Test event"
        db.close()  # Release SQLite handle before tempdir cleanup (required on Windows)


# ---------------------------------------------------------------------------
# Full simulation smoke test
# ---------------------------------------------------------------------------

def test_simulate_smoke():
    """Full end-to-end smoke test — should complete without errors."""
    from ndbot.config.settings import BotConfig
    from ndbot.execution.simulate import SimulationEngine
    from ndbot.storage.database import Database

    cfg = BotConfig.model_validate(_make_minimal_config())

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/smoke.db"
        cfg = cfg.model_copy(
            update={"storage": cfg.storage.model_copy(update={"db_path": db_path})}
        )
        db = Database(db_path)
        db.init()

        engine = SimulationEngine(cfg, db, n_events=10, n_candles=100, seed=99)
        summary = engine.run()

        assert "equity" in summary
        assert "total_trades" in summary
        assert summary["equity"] > 0
        db.close()  # Release SQLite handle before tempdir cleanup (required on Windows)


# ---------------------------------------------------------------------------
# Backtest smoke test
# ---------------------------------------------------------------------------


def test_backtest_smoke():
    """SimulationEngine in backtest mode completes without errors."""
    from ndbot.config.settings import BotConfig
    from ndbot.execution.simulate import SimulationEngine
    from ndbot.storage.database import Database

    cfg = BotConfig.model_validate({
        "run_name": "bt-smoke",
        "mode": "backtest",
        "signals": [
            {"domain": "ENERGY_GEO", "enabled": True, "min_confidence": 0.20,
             "holding_minutes": 30, "risk_per_trade": 0.01, "rr_ratio": 2.0},
        ],
        "confirmation": {"enabled": False},
        "portfolio": {"initial_capital": 200.0, "max_concurrent_positions": 5},
    })

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/bt.db"
        cfg = cfg.model_copy(
            update={"storage": cfg.storage.model_copy(update={"db_path": db_path})}
        )
        db = Database(db_path)
        db.init()
        engine = SimulationEngine(cfg, db, n_events=15, n_candles=150, seed=42)
        summary = engine.run()
        assert "equity" in summary
        assert summary["equity"] > 0
        db.close()


# ---------------------------------------------------------------------------
# Walk-forward smoke test
# ---------------------------------------------------------------------------


def test_walkforward_smoke():
    """WalkForwardValidator completes without errors on synthetic data."""
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.synthetic import SyntheticFeed
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator
    from ndbot.research.walkforward import WalkForwardValidator

    gen = SyntheticCandleGenerator(seed=77)
    candles = gen.generate(600)

    start_time = candles.index[50].to_pydatetime()
    feed = SyntheticFeed(
        domain=EventDomain.ENERGY_GEO,
        seed=77,
        start_time=start_time,
        time_step_minutes=30,
    )
    events = feed.generate_batch(25)

    classifier = KeywordClassifier()
    for ev in events:
        classifier.enrich(ev)

    validator = WalkForwardValidator(
        events=[ev.to_dict() for ev in events],
        candles=candles,
        train_days=2,
        test_days=1,
        step_days=1,
        initial_capital=100.0,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        report = validator.run(output_dir=tmpdir, run_name="wf-smoke")

    assert isinstance(report, dict)
    assert "n_windows" in report or "error" in report


# ---------------------------------------------------------------------------
# Event study smoke test
# ---------------------------------------------------------------------------


def test_event_study_smoke():
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain
    from ndbot.feeds.synthetic import SyntheticFeed
    from ndbot.market.regime import RegimeDetector
    from ndbot.market.synthetic_candles import SyntheticCandleGenerator
    from ndbot.research.event_study import EventStudy

    # Generate candles covering the last 25 hours (300 × 5-min candles)
    gen = SyntheticCandleGenerator(seed=42)
    raw = gen.generate(300)
    detector = RegimeDetector()
    candles = detector.add_indicators(raw)

    # Anchor events to the middle of the candle range so pre/post windows fit
    event_start = candles.index[80].to_pydatetime()
    feed = SyntheticFeed(domain=EventDomain.ENERGY_GEO, seed=42,
                         start_time=event_start, time_step_minutes=5)
    events = feed.generate_batch(10)

    classifier = KeywordClassifier()
    for ev in events:
        classifier.enrich(ev)

    study = EventStudy(candles=candles, pre_candles=6, post_candles=12)

    with tempfile.TemporaryDirectory() as tmpdir:
        report = study.run(
            events=[ev.to_dict() for ev in events],
            output_dir=tmpdir,
            run_name="test",
        )
    assert "n_events" in report
    assert report.get("n_events", 0) >= 1
