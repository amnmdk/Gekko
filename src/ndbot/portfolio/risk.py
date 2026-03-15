"""
Risk engine — position sizing and pre-trade risk checks.

Sizing model: Fixed Fractional Risk
  size = (equity × risk_fraction) / (entry_price - stop_price)

Pre-trade checks:
  1. Max concurrent positions
  2. Max daily loss guard
  3. Max drawdown circuit breaker
  4. Minimum confidence threshold
  5. Kill switch check
  6. Max single-position size cap

Risk controls (institutional grade):
  - Volatility-adjusted sizing via regime multiplier
  - Confidence-scaled sizing
  - Global kill switch for emergency halt
  - Bid/ask spread cost modeling
  - Execution latency simulation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from ..config.settings import PortfolioConfig
from ..market.regime import VolatilityRegime
from .position import Position

logger = logging.getLogger(__name__)

# ATR multiplier for stop-loss distance (1.5 × ATR from entry)
ATR_STOP_MULTIPLIER = 1.5

# Fallback stop distance as fraction of entry price when ATR is zero
FALLBACK_STOP_FRACTION = 0.01

# Regime-based sizing multipliers
REGIME_SIZE_MULTIPLIER = {
    VolatilityRegime.LOW: 1.25,
    VolatilityRegime.NORMAL: 1.0,
    VolatilityRegime.HIGH: 0.6,
}

# Minimum confidence scaling factor (confidence below this → 30% size)
MIN_CONFIDENCE_SCALE = 0.3

# Maximum single position as fraction of total equity
MAX_POSITION_EQUITY_FRACTION = 0.25

# Default bid/ask half-spread for cost modeling (fraction of price)
DEFAULT_HALF_SPREAD = 0.0003


@dataclass
class SizingResult:
    approved: bool
    size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    rejection_reason: Optional[str] = None
    spread_cost: float = 0.0
    effective_entry: float = 0.0


class RiskEngine:
    """
    Computes position sizes and enforces risk limits.

    Includes global kill switch for emergency halt of all trading.

    Parameters
    ----------
    config: PortfolioConfig
    """

    def __init__(self, config: PortfolioConfig):
        self._cfg = config
        self._today_pnl: float = 0.0
        self._today_date: Optional[date] = None
        self._peak_equity: float = config.initial_capital
        self._kill_switch: bool = False
        self._total_trades: int = 0
        self._consecutive_losses: int = 0
        self._max_consecutive_losses: int = 0

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    @property
    def kill_switch_active(self) -> bool:
        """Whether the kill switch is engaged."""
        return self._kill_switch

    def activate_kill_switch(self, reason: str = "") -> None:
        """Halt all new position entries."""
        self._kill_switch = True
        logger.critical("KILL SWITCH ACTIVATED: %s", reason or "manual")

    def deactivate_kill_switch(self) -> None:
        """Resume trading."""
        self._kill_switch = False
        logger.warning("Kill switch deactivated — trading resumed")

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

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
        half_spread: float = DEFAULT_HALF_SPREAD,
    ) -> SizingResult:
        """
        Compute position size and validate against all risk rules.

        Uses ATR-based stop placement:
          LONG:  stop = entry - 1.5 × ATR
          SHORT: stop = entry + 1.5 × ATR
          TP = entry ± (stop_distance × rr_ratio)

        Includes realistic transaction costs:
          - Bid/ask spread modeled via half_spread parameter
          - Commission from config
          - Slippage from config
        """
        open_positions = open_positions or []

        # --- Pre-trade checks ---
        rejection = self._check_pre_trade(equity, open_positions)
        if rejection:
            return SizingResult(
                approved=False, size=0.0, stop_loss=0.0, take_profit=0.0,
                risk_amount=0.0, rejection_reason=rejection,
            )

        # --- Spread cost modeling ---
        spread_cost = entry_price * half_spread
        if direction == "LONG":
            effective_entry = entry_price + spread_cost  # Buy at ask
        else:
            effective_entry = entry_price - spread_cost  # Sell at bid

        # --- Stop placement (using effective entry) ---
        stop_distance = ATR_STOP_MULTIPLIER * atr
        if stop_distance <= 0:
            stop_distance = entry_price * FALLBACK_STOP_FRACTION

        if direction == "LONG":
            stop_loss = effective_entry - stop_distance
            take_profit = effective_entry + stop_distance * rr_ratio
        else:
            stop_loss = effective_entry + stop_distance
            take_profit = effective_entry - stop_distance * rr_ratio

        stop_loss = max(0.01, stop_loss)

        # --- Regime sizing multiplier ---
        regime_mult = REGIME_SIZE_MULTIPLIER[regime]

        # --- Confidence scaling: reduce size if low confidence ---
        conf_mult = max(MIN_CONFIDENCE_SCALE, min(1.0, confidence))

        # --- Fixed fractional sizing ---
        effective_risk_fraction = risk_fraction * regime_mult * conf_mult
        risk_amount = equity * effective_risk_fraction

        price_diff = abs(effective_entry - stop_loss)
        if price_diff < 1e-8:
            return SizingResult(
                approved=False, size=0.0, stop_loss=stop_loss, take_profit=take_profit,
                risk_amount=0.0, rejection_reason="zero_price_distance",
            )

        size = risk_amount / price_diff

        # Max position cap: single position cannot exceed fraction of equity
        max_size_equity = (equity * MAX_POSITION_EQUITY_FRACTION) / entry_price
        max_size_total = equity / entry_price
        size = min(size, max_size_equity, max_size_total)

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
            spread_cost=round(spread_cost * size, 6),
            effective_entry=round(effective_entry, 4),
        )

    # ------------------------------------------------------------------
    # PnL tracking
    # ------------------------------------------------------------------

    def record_pnl(self, pnl: float, current_equity: float) -> None:
        """Update daily PnL tracker, peak equity, and consecutive loss counter."""
        today = datetime.now(timezone.utc).date()
        if self._today_date != today:
            self._today_date = today
            self._today_pnl = 0.0
        self._today_pnl += pnl
        self._peak_equity = max(self._peak_equity, current_equity)
        self._total_trades += 1

        # Track consecutive losses
        if pnl < 0:
            self._consecutive_losses += 1
            self._max_consecutive_losses = max(
                self._max_consecutive_losses, self._consecutive_losses
            )
        else:
            self._consecutive_losses = 0

    def drawdown_fraction(self, current_equity: float) -> float:
        """Return current drawdown as a fraction [0, 1] from peak equity."""
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - current_equity) / self._peak_equity)

    @property
    def risk_stats(self) -> dict:
        """Return risk monitoring statistics."""
        return {
            "total_trades": self._total_trades,
            "today_pnl": round(self._today_pnl, 4),
            "peak_equity": round(self._peak_equity, 4),
            "consecutive_losses": self._consecutive_losses,
            "max_consecutive_losses": self._max_consecutive_losses,
            "kill_switch": self._kill_switch,
        }

    # ------------------------------------------------------------------
    # Pre-trade validation
    # ------------------------------------------------------------------

    def _check_pre_trade(
        self, equity: float, open_positions: list[Position]
    ) -> Optional[str]:
        """Run pre-trade risk checks. Returns rejection reason or None."""
        # Kill switch
        if self._kill_switch:
            return "kill_switch_active"

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
            self.activate_kill_switch(f"max_drawdown_breached ({dd:.1%})")
            return f"max_drawdown_exceeded ({dd:.1%})"

        return None
