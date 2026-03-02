"""
Signal generator for ENERGY_GEO domain.

Strategy logic
--------------
Negative-sentiment energy/geopolitical events (attacks, blockades, sanctions)
→ SHORT oil-correlated assets (e.g. BTC as risk-off proxy, or direct OIL CFD)

Positive-sentiment events (ceasefires, production increases, new discoveries)
→ LONG

Signal strength is proportional to confidence score × sentiment magnitude.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from ..config.settings import BotConfig, SignalConfig
from ..feeds.base import EventDomain, NewsEvent
from .base import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


class EnergyGeoSignalGenerator:
    """
    Generates trade signals from ENERGY_GEO classified events.
    """

    DOMAIN = EventDomain.ENERGY_GEO

    # Keywords that strongly indicate supply disruption → SHORT
    _BEARISH_KEYWORDS = {
        "attack", "strike", "missile", "drone", "blockade", "closure",
        "sanctions", "embargo", "sabotage", "explosion", "disruption",
        "outage", "halt", "ban", "restriction", "threat", "conflict",
    }
    # Keywords that indicate supply restoration / positive outcome → LONG
    _BULLISH_KEYWORDS = {
        "ceasefire", "reopens", "resumes", "discovery", "production increase",
        "peace", "normalisation", "lifted", "agreement", "deal",
    }

    def __init__(self, config: BotConfig, signal_config: SignalConfig):
        self._config = config
        self._sig_cfg = signal_config

    def generate(self, event: NewsEvent, confidence: float) -> TradeSignal | None:
        """
        Generate a trade signal from *event* if confidence threshold met.
        Returns None if no signal should be issued.
        """
        if event.domain != self.DOMAIN:
            return None
        if confidence < self._sig_cfg.min_confidence:
            logger.debug(
                "ENERGY_GEO: confidence %.3f below threshold %.3f — skip",
                confidence, self._sig_cfg.min_confidence,
            )
            return None

        direction = self._determine_direction(event)
        if direction == SignalDirection.FLAT:
            return None

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
            "ENERGY_GEO signal: %s %s conf=%.3f | %s",
            direction.value, symbol, confidence, event.headline[:60],
        )
        return signal

    def _determine_direction(self, event: NewsEvent) -> SignalDirection:
        text = (event.headline + " " + event.summary).lower()
        bearish_hits = sum(1 for kw in self._BEARISH_KEYWORDS if kw in text)
        bullish_hits = sum(1 for kw in self._BULLISH_KEYWORDS if kw in text)

        # Use sentiment score as tiebreaker
        if bearish_hits > bullish_hits or event.sentiment_score < -0.3:
            return SignalDirection.SHORT
        elif bullish_hits > bearish_hits or event.sentiment_score > 0.3:
            return SignalDirection.LONG
        return SignalDirection.FLAT
