"""
Position data model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CloseReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TIME_STOP = "TIME_STOP"
    MANUAL = "MANUAL"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"


@dataclass
class Position:
    """
    Represents a single open or closed trading position.
    All prices in quote currency (e.g. USDT).
    """
    position_id: str
    symbol: str
    direction: str          # "LONG" | "SHORT"
    entry_price: float
    size: float             # Base currency units (e.g. BTC)
    stop_loss: float
    take_profit: float
    entry_time: datetime
    holding_minutes: int    # Maximum hold duration
    signal_id: str
    domain: str

    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    close_reason: Optional[CloseReason] = None
    realised_pnl: float = 0.0
    commission_paid: float = 0.0

    # Risk metadata
    risk_amount: float = 0.0    # USD amount at risk
    confidence: float = 0.0

    def notional_value(self) -> float:
        return self.entry_price * self.size

    def unrealised_pnl(self, current_price: float) -> float:
        if self.direction == "LONG":
            return (current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - current_price) * self.size

    def is_expired(self, current_time: datetime) -> bool:
        elapsed = (current_time - self.entry_time).total_seconds() / 60
        return elapsed >= self.holding_minutes

    def should_stop_loss(self, current_price: float) -> bool:
        if self.direction == "LONG":
            return current_price <= self.stop_loss
        else:
            return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        if self.direction == "LONG":
            return current_price >= self.take_profit
        else:
            return current_price <= self.take_profit

    def close(
        self,
        exit_price: float,
        exit_time: datetime,
        reason: CloseReason,
        commission_rate: float = 0.001,
    ) -> None:
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.close_reason = reason
        self.status = PositionStatus.CLOSED

        if self.direction == "LONG":
            gross_pnl = (exit_price - self.entry_price) * self.size
        else:
            gross_pnl = (self.entry_price - exit_price) * self.size

        # Commission on entry and exit
        entry_comm = self.entry_price * self.size * commission_rate
        exit_comm = exit_price * self.size * commission_rate
        self.commission_paid = entry_comm + exit_comm
        self.realised_pnl = gross_pnl - self.commission_paid

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "size": self.size,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "entry_time": self.entry_time.isoformat(),
            "holding_minutes": self.holding_minutes,
            "signal_id": self.signal_id,
            "domain": self.domain,
            "status": self.status.value,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "close_reason": self.close_reason.value if self.close_reason else None,
            "realised_pnl": round(self.realised_pnl, 6),
            "commission_paid": round(self.commission_paid, 6),
            "risk_amount": self.risk_amount,
            "confidence": self.confidence,
        }
