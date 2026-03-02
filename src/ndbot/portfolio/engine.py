"""
Portfolio engine — orchestrates position lifecycle.

Responsibilities:
  - Accept signals from signal generators
  - Apply risk engine sizing
  - Apply confirmation engine check
  - Open positions
  - Monitor open positions for exits (SL / TP / time-stop)
  - Track equity curve
  - Compute performance metrics on demand
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..config.settings import BotConfig
from ..market.data import MarketDataFeed
from ..market.regime import VolatilityRegime
from ..signals.base import SignalDirection, TradeSignal
from ..signals.confirmation import ConfirmationEngine
from .metrics import PerformanceReport, PortfolioMetrics
from .position import CloseReason, Position, PositionStatus
from .risk import RiskEngine, SizingResult

logger = logging.getLogger(__name__)


class PortfolioEngine:
    """
    Central portfolio management engine.

    Parameters
    ----------
    config: BotConfig
    market: MarketDataFeed
    """

    def __init__(self, config: BotConfig, market: MarketDataFeed):
        self._config = config
        self._pc = config.portfolio
        self._market = market
        self._risk = RiskEngine(config.portfolio)
        self._confirmation = ConfirmationEngine(config.confirmation)

        self._equity: float = config.portfolio.initial_capital
        self._equity_curve: list[float] = [config.portfolio.initial_capital]
        self._positions: list[Position] = []
        self._closed_pnls: list[float] = []
        self._trade_holding_times: list[float] = []

    # ------------------------------------------------------------------
    # Signal intake
    # ------------------------------------------------------------------

    def on_signal(self, signal: TradeSignal) -> Optional[Position]:
        """
        Process a trade signal. Returns opened Position or None.
        """
        if signal.direction == SignalDirection.FLAT:
            return None

        current_price = self._market.current_price()
        atr = self._market.current_atr()
        regime = self._market.volatility_regime()
        candles = self._market.candles

        # --- Confirmation check ---
        if self._config.confirmation.enabled and len(candles) > 0:
            conf_result = self._confirmation.check(signal, candles)
            signal.confirmed = conf_result.passed
            if not conf_result.passed:
                logger.info(
                    "Signal %s rejected by confirmation: %s",
                    signal.signal_id, conf_result.reason,
                )
                return None
        else:
            signal.confirmed = True

        signal.regime = regime.value

        # --- Risk sizing ---
        open_positions = [p for p in self._positions if p.status == PositionStatus.OPEN]

        sig_config = self._get_signal_config(signal.domain)
        rr_ratio = sig_config.rr_ratio if sig_config else 2.0
        risk_fraction = signal.risk_fraction

        sizing = self._risk.compute_sizing(
            equity=self._equity,
            entry_price=current_price,
            direction=signal.direction.value,
            atr=atr if atr > 0 else current_price * 0.01,
            risk_fraction=risk_fraction,
            rr_ratio=rr_ratio,
            regime=regime,
            open_positions=open_positions,
            confidence=signal.confidence,
        )

        if not sizing.approved:
            logger.info(
                "Signal %s rejected by risk engine: %s",
                signal.signal_id, sizing.rejection_reason,
            )
            return None

        # --- Open position ---
        position = self._open_position(signal, current_price, sizing)
        self._positions.append(position)
        logger.info(
            "POSITION OPENED: %s %s %s @ %.4f | size=%.6f | SL=%.4f | TP=%.4f",
            position.position_id, position.direction, position.symbol,
            position.entry_price, position.size,
            position.stop_loss, position.take_profit,
        )
        return position

    # ------------------------------------------------------------------
    # Position monitoring
    # ------------------------------------------------------------------

    def update(self, current_time: Optional[datetime] = None) -> list[Position]:
        """
        Check all open positions for exit conditions.
        Returns list of positions closed in this update.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        current_price = self._market.current_price()
        if current_price <= 0:
            return []

        closed_this_update: list[Position] = []
        for pos in self._positions:
            if pos.status != PositionStatus.OPEN:
                continue

            close_reason = self._check_exit(pos, current_price, current_time)
            if close_reason is not None:
                exit_price = self._apply_slippage(current_price)
                pos.close(
                    exit_price=exit_price,
                    exit_time=current_time,
                    reason=close_reason,
                    commission_rate=self._pc.commission_rate,
                )
                self._equity += pos.realised_pnl
                self._equity_curve.append(self._equity)
                self._closed_pnls.append(pos.realised_pnl)
                self._trade_holding_times.append(
                    (pos.exit_time - pos.entry_time).total_seconds() / 60
                )
                self._risk.record_pnl(pos.realised_pnl, self._equity)
                closed_this_update.append(pos)
                logger.info(
                    "POSITION CLOSED: %s %s | PnL=%.4f | reason=%s",
                    pos.position_id, pos.direction,
                    pos.realised_pnl, close_reason.value,
                )

        return closed_this_update

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def equity_curve(self) -> list[float]:
        return list(self._equity_curve)

    @property
    def positions(self) -> list[Position]:
        return list(self._positions)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions if p.status == PositionStatus.OPEN]

    @property
    def closed_positions(self) -> list[Position]:
        return [p for p in self._positions if p.status == PositionStatus.CLOSED]

    def performance(self) -> PerformanceReport:
        avg_hold = (
            sum(self._trade_holding_times) / len(self._trade_holding_times)
            if self._trade_holding_times else 60.0
        )
        return PortfolioMetrics.compute(
            closed_pnls=self._closed_pnls,
            equity_curve=self._equity_curve,
            initial_capital=self._pc.initial_capital,
            holding_minutes_avg=avg_hold,
        )

    def summary(self) -> dict:
        p = self.performance()
        return {
            "equity": round(self._equity, 4),
            "initial_capital": self._pc.initial_capital,
            "return_pct": round((self._equity / self._pc.initial_capital - 1) * 100, 4),
            "open_positions": len(self.open_positions),
            "total_trades": p.total_trades,
            **p.to_dict(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_position(
        self, signal: TradeSignal, entry_price: float, sizing: SizingResult
    ) -> Position:
        pos_id = hashlib.sha256(
            f"{signal.signal_id}{entry_price}".encode()
        ).hexdigest()[:12]
        entry_price_with_slip = self._apply_slippage(entry_price)

        return Position(
            position_id=pos_id,
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=entry_price_with_slip,
            size=sizing.size,
            stop_loss=sizing.stop_loss,
            take_profit=sizing.take_profit,
            entry_time=datetime.now(timezone.utc),
            holding_minutes=signal.holding_minutes,
            signal_id=signal.signal_id,
            domain=signal.domain,
            risk_amount=sizing.risk_amount,
            confidence=signal.confidence,
        )

    def _apply_slippage(self, price: float) -> float:
        return price * (1 + self._pc.slippage_rate)

    def _check_exit(
        self, pos: Position, current_price: float, current_time: datetime
    ) -> Optional[CloseReason]:
        if pos.should_stop_loss(current_price):
            return CloseReason.STOP_LOSS
        if pos.should_take_profit(current_price):
            return CloseReason.TAKE_PROFIT
        if pos.is_expired(current_time):
            return CloseReason.TIME_STOP

        # Check max daily loss
        daily_loss_limit = self._equity * self._pc.max_daily_loss_pct
        if self._risk._today_pnl < -daily_loss_limit:
            return CloseReason.MAX_DAILY_LOSS

        # Check drawdown circuit breaker
        if self._risk.drawdown_fraction(self._equity) >= self._pc.max_drawdown_pct:
            return CloseReason.MAX_DRAWDOWN

        return None

    def _get_signal_config(self, domain: str):
        for sc in self._config.signals:
            if sc.domain == domain:
                return sc
        return None
