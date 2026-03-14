"""
Base types for trade signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class TradeSignal:
    """
    A trade signal emitted by a domain signal generator.
    Carries full audit trail back to the originating event.
    """
    signal_id: str
    domain: str                     # "ENERGY_GEO" | "AI_RELEASES"
    direction: SignalDirection
    symbol: str
    confidence: float               # [0, 1] composite confidence score
    entry_price: Optional[float]    # None = use market price
    stop_loss: Optional[float]
    take_profit: Optional[float]
    holding_minutes: int
    risk_fraction: float            # Fraction of equity to risk
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Audit
    event_id: str = ""
    event_headline: str = ""
    keywords: list[str] = field(default_factory=list)
    regime: str = "UNKNOWN"         # LOW / NORMAL / HIGH volatility regime
    confirmed: bool = False         # Has confirmation engine approved?
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "domain": self.domain,
            "direction": self.direction.value,
            "symbol": self.symbol,
            "confidence": round(self.confidence, 4),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "holding_minutes": self.holding_minutes,
            "risk_fraction": self.risk_fraction,
            "created_at": self.created_at.isoformat(),
            "event_id": self.event_id,
            "event_headline": self.event_headline,
            "keywords": self.keywords,
            "regime": self.regime,
            "confirmed": self.confirmed,
            "metadata": self.metadata,
        }
