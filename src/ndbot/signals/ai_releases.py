"""
Signal generator for AI_RELEASES domain.

Strategy logic
--------------
Major AI product launches (new models, funding rounds, open-source releases)
→ LONG on risk assets (BTC/ETH as proxy for tech sentiment)

Negative AI events (security incidents, regulatory bans, outages)
→ SHORT (risk-off / tech sell-off proxy)

Rationale: large AI announcements drive significant retail + institutional
sentiment shifts in crypto and tech assets within the first hour.
This is a momentum/sentiment capture strategy, NOT a fundamental play.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from ..config.settings import BotConfig, SignalConfig
from ..feeds.base import EventDomain, NewsEvent
from .base import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


class AIReleasesSignalGenerator:
    """
    Generates trade signals from AI_RELEASES classified events.
    """

    DOMAIN = EventDomain.AI_RELEASES

    _BULLISH_KEYWORDS = {
        "releases", "launch", "launches", "released", "announced",
        "open-source", "raises", "funding", "valuation", "achieves",
        "surpasses", "state-of-the-art", "breakthrough", "wins",
        "award", "generally available", "ga release",
    }
    _BEARISH_KEYWORDS = {
        "vulnerability", "jailbreak", "outage", "ban", "regulatory action",
        "investigation", "security breach", "data leak", "fine",
        "shutdown", "blocked", "restriction",
    }

    # Labs whose releases command higher importance
    _TOP_TIER_LABS = {"openai", "anthropic", "deepmind", "google"}

    def __init__(self, config: BotConfig, signal_config: SignalConfig):
        self._config = config
        self._sig_cfg = signal_config

    def generate(self, event: NewsEvent, confidence: float) -> TradeSignal | None:
        """Generate a trade signal from *event* if confidence threshold met."""
        if event.domain != self.DOMAIN:
            return None
        if confidence < self._sig_cfg.min_confidence:
            logger.debug(
                "AI_RELEASES: confidence %.3f below threshold %.3f — skip",
                confidence, self._sig_cfg.min_confidence,
            )
            return None

        direction = self._determine_direction(event)
        if direction == SignalDirection.FLAT:
            return None

        # Apply tier multiplier for top-tier labs
        confidence = self._apply_tier_boost(event, confidence)

        symbol = self._config.market.symbol
        sig_id = hashlib.sha256(
            f"{event.event_id}{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        signal = TradeSignal(
            signal_id=sig_id,
            domain=self.DOMAIN.value,
            direction=direction,
            symbol=symbol,
            confidence=confidence,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            holding_minutes=self._sig_cfg.holding_minutes,
            risk_fraction=self._sig_cfg.risk_per_trade,
            event_id=event.event_id,
            event_headline=event.headline,
            keywords=event.keywords_matched,
        )
        logger.info(
            "AI_RELEASES signal: %s %s conf=%.3f | %s",
            direction.value, symbol, confidence, event.headline[:60],
        )
        return signal

    def _determine_direction(self, event: NewsEvent) -> SignalDirection:
        """Determine LONG/SHORT/FLAT from keyword hits and sentiment."""
        text = (event.headline + " " + event.summary).lower()
        bullish_hits = sum(1 for kw in self._BULLISH_KEYWORDS if kw in text)
        bearish_hits = sum(1 for kw in self._BEARISH_KEYWORDS if kw in text)

        if bullish_hits > bearish_hits or event.sentiment_score > 0.3:
            return SignalDirection.LONG
        elif bearish_hits > bullish_hits or event.sentiment_score < -0.3:
            return SignalDirection.SHORT
        return SignalDirection.FLAT

    def _apply_tier_boost(self, event: NewsEvent, confidence: float) -> float:
        """Boost confidence by 15% if event mentions a top-tier AI lab."""
        text = (event.headline + " " + event.summary).lower()
        for lab in self._TOP_TIER_LABS:
            if lab in text:
                confidence = min(0.95, confidence * 1.15)
                break
        return round(confidence, 4)
