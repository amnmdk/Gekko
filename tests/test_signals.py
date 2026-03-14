"""
Signal generation pipeline tests.

Covers:
- EnergyGeoSignalGenerator: bearish/bullish events → SHORT/LONG
- AIReleasesSignalGenerator: launches/incidents → LONG/SHORT
- ConfidenceModel: always returns values in [0, 1]
- Below-threshold filtering: signal returns None when confidence < min_confidence
- KeywordClassifier: domain assignment and sentiment scoring
- EntityExtractor: organisation / location NER
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    domain_str: str,
    headline: str,
    summary: str = "",
    sentiment: float = 0.0,
    importance: float = 0.7,
    credibility: float = 1.5,
) -> object:
    from ndbot.feeds.base import EventDomain, NewsEvent

    domain_map = {
        "ENERGY_GEO": EventDomain.ENERGY_GEO,
        "AI_RELEASES": EventDomain.AI_RELEASES,
        "UNKNOWN": EventDomain.UNKNOWN,
    }
    return NewsEvent(
        event_id="test-signal-event",
        domain=domain_map[domain_str],
        headline=headline,
        summary=summary,
        source="test",
        url="http://test.com",
        published_at=datetime.now(timezone.utc),
        sentiment_score=sentiment,
        importance_score=importance,
        credibility_weight=credibility,
        keywords_matched=["test"],
    )


def _make_energy_geo_gen(min_confidence: float = 0.1):
    from ndbot.config.settings import BotConfig, SignalConfig
    from ndbot.signals.energy_geo import EnergyGeoSignalGenerator

    sig_cfg = SignalConfig(
        domain="ENERGY_GEO",
        enabled=True,
        min_confidence=min_confidence,
        holding_minutes=60,
        risk_per_trade=0.01,
        rr_ratio=2.0,
    )
    base_cfg = BotConfig.model_validate(
        {
            "run_name": "t",
            "mode": "simulate",
            "signals": [sig_cfg.model_dump()],
            "confirmation": {"enabled": False},
        }
    )
    return EnergyGeoSignalGenerator(base_cfg, sig_cfg)


def _make_ai_releases_gen(min_confidence: float = 0.1):
    from ndbot.config.settings import BotConfig, SignalConfig
    from ndbot.signals.ai_releases import AIReleasesSignalGenerator

    sig_cfg = SignalConfig(
        domain="AI_RELEASES",
        enabled=True,
        min_confidence=min_confidence,
        holding_minutes=45,
        risk_per_trade=0.01,
        rr_ratio=2.0,
    )
    base_cfg = BotConfig.model_validate(
        {
            "run_name": "t",
            "mode": "simulate",
            "signals": [sig_cfg.model_dump()],
            "confirmation": {"enabled": False},
        }
    )
    return AIReleasesSignalGenerator(base_cfg, sig_cfg)


# ---------------------------------------------------------------------------
# EnergyGeo signals
# ---------------------------------------------------------------------------


def test_energy_geo_bearish_yields_short() -> None:
    """Supply disruption events should generate SHORT signals."""
    gen = _make_energy_geo_gen()
    event = _make_event(
        "ENERGY_GEO",
        "Iran sanctions disrupt Hormuz strait shipping lanes",
        sentiment=-0.7,
    )
    signal = gen.generate(event, confidence=0.7)

    assert signal is not None
    assert signal.direction == "SHORT"
    assert signal.confidence == pytest.approx(0.7)


def test_energy_geo_bullish_yields_long() -> None:
    """Ceasefire / resumption events should generate LONG signals."""
    gen = _make_energy_geo_gen()
    event = _make_event(
        "ENERGY_GEO",
        "Libya ceasefire agreement lifts oil production embargo",
        sentiment=0.7,
    )
    signal = gen.generate(event, confidence=0.65)

    assert signal is not None
    assert signal.direction == "LONG"


def test_energy_geo_below_threshold_returns_none() -> None:
    """Confidence below min_confidence must return None."""
    gen = _make_energy_geo_gen(min_confidence=0.80)
    event = _make_event("ENERGY_GEO", "Minor pipeline maintenance update", sentiment=0.1)
    signal = gen.generate(event, confidence=0.30)

    assert signal is None


def test_energy_geo_wrong_domain_returns_none() -> None:
    """ENERGY_GEO generator must not handle AI_RELEASES events."""
    gen = _make_energy_geo_gen()
    event = _make_event("AI_RELEASES", "OpenAI launches GPT-5", sentiment=0.8)
    signal = gen.generate(event, confidence=0.9)

    assert signal is None


def test_energy_geo_signal_has_risk_fields() -> None:
    """Generated signal must carry risk fraction and holding minutes."""
    gen = _make_energy_geo_gen()
    event = _make_event("ENERGY_GEO", "Houthi drone attack on oil tanker", sentiment=-0.8)
    signal = gen.generate(event, confidence=0.75)

    assert signal is not None
    assert signal.risk_fraction > 0
    assert signal.holding_minutes > 0


# ---------------------------------------------------------------------------
# AI Releases signals
# ---------------------------------------------------------------------------


def test_ai_releases_launch_yields_long() -> None:
    """AI product launches should generate LONG (risk-on) signals."""
    gen = _make_ai_releases_gen()
    event = _make_event(
        "AI_RELEASES",
        "OpenAI launches GPT-5 with major breakthrough capabilities",
        sentiment=0.8,
    )
    signal = gen.generate(event, confidence=0.75)

    assert signal is not None
    assert signal.direction == "LONG"


def test_ai_releases_incident_yields_short() -> None:
    """AI safety incidents / regulatory bans should generate SHORT signals."""
    gen = _make_ai_releases_gen()
    event = _make_event(
        "AI_RELEASES",
        "EU regulator bans AI system, investigation launched",
        sentiment=-0.7,
    )
    signal = gen.generate(event, confidence=0.70)

    assert signal is not None
    assert signal.direction == "SHORT"


def test_ai_releases_below_threshold_returns_none() -> None:
    gen = _make_ai_releases_gen(min_confidence=0.90)
    event = _make_event("AI_RELEASES", "Minor AI model update released", sentiment=0.1)
    signal = gen.generate(event, confidence=0.35)

    assert signal is None


# ---------------------------------------------------------------------------
# Confidence model
# ---------------------------------------------------------------------------


def test_confidence_model_always_in_range() -> None:
    """ConfidenceModel.score() must always return a value in [0.0, 1.0]."""
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.signals.confidence_model import ConfidenceModel

    model = ConfidenceModel()
    test_cases = [
        {"sentiment": 0.9, "importance": 0.9, "credibility": 2.0},
        {"sentiment": -0.9, "importance": 0.1, "credibility": 0.5},
        {"sentiment": 0.0, "importance": 0.5, "credibility": 1.0},
        {"sentiment": 0.3, "importance": 0.8, "credibility": 1.8},
        {"sentiment": -1.0, "importance": 1.0, "credibility": 2.0},  # Max inputs
        {"sentiment": 0.0, "importance": 0.0, "credibility": 0.0},  # Min inputs
    ]
    for tc in test_cases:
        ev = NewsEvent(
            event_id="conf-test",
            domain=EventDomain.ENERGY_GEO,
            headline="Test event",
            summary="",
            source="test",
            url="",
            published_at=datetime.now(timezone.utc),
            sentiment_score=tc["sentiment"],
            importance_score=tc["importance"],
            credibility_weight=tc["credibility"],
        )
        score = model.score(ev)
        assert 0.0 <= score <= 1.0, (
            f"Score {score} out of [0, 1] for inputs {tc}"
        )


def test_confidence_model_higher_importance_higher_score() -> None:
    """Higher importance should generally yield a higher confidence score."""
    from ndbot.feeds.base import EventDomain, NewsEvent
    from ndbot.signals.confidence_model import ConfidenceModel

    model = ConfidenceModel()

    def make_ev(importance: float) -> NewsEvent:
        return NewsEvent(
            event_id="imp-test",
            domain=EventDomain.ENERGY_GEO,
            headline="Test",
            summary="",
            source="test",
            url="",
            published_at=datetime.now(timezone.utc),
            sentiment_score=0.5,
            importance_score=importance,
            credibility_weight=1.0,
        )

    low_score = model.score(make_ev(0.1))
    high_score = model.score(make_ev(0.9))
    assert high_score >= low_score, "Higher importance must yield >= score"


# ---------------------------------------------------------------------------
# Keyword classifier
# ---------------------------------------------------------------------------


def test_classifier_energy_geo_detection() -> None:
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain, NewsEvent

    ev = NewsEvent(
        event_id="kc-1",
        domain=EventDomain.UNKNOWN,
        headline="Houthi missiles strike Saudi Aramco oil tanker in Red Sea",
        summary="",
        source="test",
        url="",
        published_at=datetime.now(timezone.utc),
    )
    KeywordClassifier().enrich(ev)

    assert ev.domain == EventDomain.ENERGY_GEO
    assert len(ev.keywords_matched) > 0
    assert ev.sentiment_score < 0  # Negative event


def test_classifier_ai_releases_detection() -> None:
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain, NewsEvent

    ev = NewsEvent(
        event_id="kc-2",
        domain=EventDomain.UNKNOWN,
        headline="Anthropic launches Claude 4 with new reasoning capabilities",
        summary="Model achieves state-of-the-art performance.",
        source="test",
        url="",
        published_at=datetime.now(timezone.utc),
    )
    KeywordClassifier().enrich(ev)

    assert ev.domain == EventDomain.AI_RELEASES
    assert ev.sentiment_score > 0  # Positive event


def test_classifier_no_crash_on_unknown_text() -> None:
    """Classifier must not crash on arbitrary text."""
    from ndbot.classifier.keyword_classifier import KeywordClassifier
    from ndbot.feeds.base import EventDomain, NewsEvent

    ev = NewsEvent(
        event_id="kc-3",
        domain=EventDomain.UNKNOWN,
        headline="Local bakery wins best croissant award",
        summary="",
        source="test",
        url="",
        published_at=datetime.now(timezone.utc),
    )
    # Should not raise
    KeywordClassifier().enrich(ev)
    assert ev.domain is not None  # Domain is set to something


# ---------------------------------------------------------------------------
# Entity extractor
# ---------------------------------------------------------------------------


def test_entity_extractor_finds_organizations() -> None:
    from ndbot.classifier.entity_extractor import EntityExtractor

    entities = EntityExtractor().extract(
        "Saudi Aramco and OPEC debate supply cuts at Vienna summit"
    )
    assert "ORG" in entities
    org_names_upper = [o.upper() for o in entities["ORG"]]
    assert any("OPEC" in name or "ARAMCO" in name for name in org_names_upper)


def test_entity_extractor_finds_locations() -> None:
    from ndbot.classifier.entity_extractor import EntityExtractor

    entities = EntityExtractor().extract(
        "Iran closes the Strait of Hormuz to tanker traffic"
    )
    assert "LOCATION" in entities
    locations_upper = [loc.upper() for loc in entities["LOCATION"]]
    assert any("IRAN" in loc or "HORMUZ" in loc for loc in locations_upper)


def test_entity_extractor_no_crash_on_empty() -> None:
    from ndbot.classifier.entity_extractor import EntityExtractor

    entities = EntityExtractor().extract("")
    assert isinstance(entities, dict)


def test_entity_extractor_no_crash_on_numbers() -> None:
    from ndbot.classifier.entity_extractor import EntityExtractor

    entities = EntityExtractor().extract("12345 67890 !!!")
    assert isinstance(entities, dict)
