"""
Confirmation engine — market-side validation before order entry.

Checks one or more technical conditions before allowing a signal to
proceed to the portfolio engine. All thresholds are configurable.

Conditions (any one must pass):
  1. Breakout: price exceeds recent high (LONG) or below recent low (SHORT)
  2. Volume spike: current volume exceeds N-period average × multiplier
  3. Volatility expansion: current ATR > recent average ATR × multiplier
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..config.settings import ConfirmationConfig
from .base import SignalDirection, TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationResult:
    passed: bool
    reason: str
    details: dict


class ConfirmationEngine:
    """
    Validates a trade signal against current market conditions.

    Parameters
    ----------
    config: ConfirmationConfig
    candles: pd.DataFrame
        Must contain columns: open, high, low, close, volume, atr
        Indexed by datetime (UTC). Most recent candle is last row.
    """

    def __init__(self, config: ConfirmationConfig):
        self._cfg = config

    def check(
        self,
        signal: TradeSignal,
        candles: pd.DataFrame,
    ) -> ConfirmationResult:
        """
        Run all confirmation checks. Returns True if ANY check passes
        (when confirmation is enabled).
        """
        if not self._cfg.enabled:
            return ConfirmationResult(
                passed=True,
                reason="confirmation_disabled",
                details={},
            )

        if len(candles) < self._cfg.lookback_candles:
            return ConfirmationResult(
                passed=False,
                reason="insufficient_candle_history",
                details={"have": len(candles), "need": self._cfg.lookback_candles},
            )

        results = {}
        results["breakout"] = self._check_breakout(signal, candles)
        results["volume_spike"] = self._check_volume_spike(candles)
        results["volatility_expansion"] = self._check_volatility_expansion(candles)

        any_passed = any(results[k]["passed"] for k in results)
        summary = "; ".join(
            f"{k}={'PASS' if v['passed'] else 'FAIL'}" for k, v in results.items()
        )
        reason = "any_confirmed" if any_passed else "no_confirmation"
        return ConfirmationResult(passed=any_passed, reason=reason, details=results)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_breakout(
        self, signal: TradeSignal, candles: pd.DataFrame
    ) -> dict:
        lb = self._cfg.lookback_candles
        lookback = candles.iloc[-lb - 1 : -1]
        current_close = float(candles["close"].iloc[-1])
        threshold = self._cfg.breakout_threshold

        if signal.direction == SignalDirection.LONG:
            reference = float(lookback["high"].max())
            required = reference * (1 + threshold)
            passed = current_close >= required
            return {
                "passed": passed,
                "current_close": current_close,
                "reference_high": reference,
                "required": required,
            }
        else:  # SHORT
            reference = float(lookback["low"].min())
            required = reference * (1 - threshold)
            passed = current_close <= required
            return {
                "passed": passed,
                "current_close": current_close,
                "reference_low": reference,
                "required": required,
            }

    def _check_volume_spike(self, candles: pd.DataFrame) -> dict:
        lb = self._cfg.lookback_candles
        if "volume" not in candles.columns:
            return {"passed": False, "reason": "no_volume_data"}
        recent_vol = candles["volume"].iloc[-lb - 1 : -1]
        avg_vol = float(recent_vol.mean())
        current_vol = float(candles["volume"].iloc[-1])
        multiplier = self._cfg.volume_spike_multiplier
        passed = (avg_vol > 0) and (current_vol >= avg_vol * multiplier)
        return {
            "passed": passed,
            "current_volume": current_vol,
            "avg_volume": avg_vol,
            "required": avg_vol * multiplier,
        }

    def _check_volatility_expansion(self, candles: pd.DataFrame) -> dict:
        if "atr" not in candles.columns:
            return {"passed": False, "reason": "no_atr_data"}
        lb = self._cfg.lookback_candles
        recent_atr = candles["atr"].iloc[-lb - 1 : -1]
        avg_atr = float(recent_atr.mean())
        current_atr = float(candles["atr"].iloc[-1])
        multiplier = self._cfg.volatility_expansion_multiplier
        passed = (avg_atr > 0) and (current_atr >= avg_atr * multiplier)
        return {
            "passed": passed,
            "current_atr": current_atr,
            "avg_atr": avg_atr,
            "required": avg_atr * multiplier,
        }
