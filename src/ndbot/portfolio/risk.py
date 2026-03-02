"""
Risk engine — position sizing and pre-trade risk checks.

Sizing model: Fixed Fractional Risk
  size = (equity × risk_fraction) / (entry_price - stop_price)

Pre-trade checks:
  1. Max concurrent positions
  2. Max daily loss guard
  3. Max drawdown circuit breaker
  4. Minimum confidence threshold
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from ..config.settings import PortfolioConfig
from ..market.regime import VolatilityRegime, RegimeDetector
from .position import Position

logger = logging.getLogger(__name__)


@dataclass
class SizingResult:
    approved: bool
    size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    rejection_reason: Optional[str] = None


class RiskEngine:
    """
    Computes position sizes and enforces risk limits.

    Parameters
    ----------
    config: PortfolioConfig
    """

    def __init__(self, config: PortfolioConfig):
        self._cfg = config
        self._today_pnl: float = 0.0
        self._today_date: Optional[date] = None
        self._peak_equity: float = config.initial_capital

    def compute_sizing(
        self,
        equity: float,
        entry_price: float,
        direction: str,
        atr: float,
        risk_fraction: float,
        rr_ratio: float,
        regime: VolatilityRegime = VolatilityRegime.NORMAL,
        open_positions: Optional[list[Position]] = None,
        confidence: float = 1.0,
    ) -> SizingResult:
        """
        Compute position size and validate against all risk rules.

        Uses ATR-based stop placement:
          LONG:  stop = entry - 1.5 × ATR
          SHORT: stop = entry + 1.5 × ATR
          TP = entry ± (stop_distance × rr_ratio)
        """
        open_positions = open_positions or []

        # --- Pre-trade checks ---
        rejection = self._check_pre_trade(equity, open_positions)
        if rejection:
            return SizingResult(
                approved=False, size=0.0, stop_loss=0.0, take_profit=0.0,
                risk_amount=0.0, rejection_reason=rejection,
            )

        # --- Stop placement ---
        stop_distance = 1.5 * atr
        if stop_distance <= 0:
            stop_distance = entry_price * 0.01  # fallback: 1%

        if direction == "LONG":
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + stop_distance * rr_ratio
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - stop_distance * rr_ratio

        stop_loss = max(0.01, stop_loss)

        # --- Regime sizing multiplier ---
        regime_mult = {
            VolatilityRegime.LOW: 1.25,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.HIGH: 0.6,
        }[regime]

        # --- Confidence scaling: reduce size if low confidence ---
        conf_mult = max(0.3, min(1.0, confidence))

        # --- Fixed fractional sizing ---
        effective_risk_fraction = risk_fraction * regime_mult * conf_mult
        risk_amount = equity * effective_risk_fraction

        price_diff = abs(entry_price - stop_loss)
        if price_diff < 1e-8:
            return SizingResult(
                approved=False, size=0.0, stop_loss=stop_loss, take_profit=take_profit,
                risk_amount=0.0, rejection_reason="zero_price_distance",
            )

        size = risk_amount / price_diff

        # Sanity: size should not exceed 100% of equity / entry_price
        max_size = equity / entry_price
        size = min(size, max_size)

        if size <= 0:
            return SizingResult(
                approved=False, size=0.0, stop_loss=stop_loss, take_profit=take_profit,
                risk_amount=0.0, rejection_reason="computed_size_zero",
            )

        return SizingResult(
            approved=True,
            size=round(size, 6),
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            risk_amount=round(risk_amount, 4),
        )

    def record_pnl(self, pnl: float, current_equity: float) -> None:
        """Update daily PnL tracker and peak equity."""
        today = datetime.now(timezone.utc).date()
        if self._today_date != today:
            self._today_date = today
            self._today_pnl = 0.0
        self._today_pnl += pnl
        self._peak_equity = max(self._peak_equity, current_equity)

    def drawdown_fraction(self, current_equity: float) -> float:
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - current_equity) / self._peak_equity)

    def _check_pre_trade(
        self, equity: float, open_positions: list[Position]
    ) -> Optional[str]:
        # Max concurrent positions
        n_open = len([p for p in open_positions if p.status.value == "OPEN"])
        if n_open >= self._cfg.max_concurrent_positions:
            return f"max_concurrent_positions_reached ({n_open})"

        # Max daily loss
        daily_loss_limit = equity * self._cfg.max_daily_loss_pct
        if self._today_pnl < -daily_loss_limit:
            return f"max_daily_loss_exceeded (today={self._today_pnl:.2f})"

        # Max drawdown circuit breaker
        dd = self.drawdown_fraction(equity)
        if dd >= self._cfg.max_drawdown_pct:
            return f"max_drawdown_exceeded ({dd:.1%})"

        return None
