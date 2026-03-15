"""
Regime-Aware Strategy Engine (Step 8).

Strategies adapt behaviour based on detected market regimes:

  Regime types:
    1. Volatility regime — LOW / NORMAL / HIGH
    2. Macro regime — EXPANSION / CONTRACTION / TRANSITION
    3. Liquidity regime — ABUNDANT / NORMAL / SCARCE

  Adaptations:
    - Position sizing scales with regime
    - Signal thresholds adjust per regime
    - Stop-loss distances widen in high-vol
    - Signal weights change across regimes
    - Certain signals disabled in specific regimes

  Integrates with existing RegimeDetector and RiskEngine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class MacroRegime(str, Enum):
    EXPANSION = "EXPANSION"
    CONTRACTION = "CONTRACTION"
    TRANSITION = "TRANSITION"


class LiquidityRegime(str, Enum):
    ABUNDANT = "ABUNDANT"
    NORMAL = "NORMAL"
    SCARCE = "SCARCE"


@dataclass
class RegimeState:
    """Current multi-dimensional regime classification."""

    timestamp: str = ""
    volatility: str = "NORMAL"    # LOW, NORMAL, HIGH
    macro: str = "EXPANSION"       # EXPANSION, CONTRACTION, TRANSITION
    liquidity: str = "NORMAL"      # ABUNDANT, NORMAL, SCARCE
    confidence: float = 0.5
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "volatility": self.volatility,
            "macro": self.macro,
            "liquidity": self.liquidity,
            "confidence": round(self.confidence, 4),
            "details": self.details,
        }


@dataclass
class RegimeAdaptation:
    """Adaptation parameters for current regime."""

    size_multiplier: float = 1.0
    signal_threshold: float = 0.6
    stop_distance_multiplier: float = 1.0
    max_positions: int = 5
    enabled_signals: list[str] = field(default_factory=list)
    disabled_signals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# Default adaptation rules per volatility regime
_VOL_ADAPTATIONS = {
    "LOW": {
        "size_multiplier": 1.25,
        "signal_threshold": 0.55,
        "stop_distance_multiplier": 0.8,
        "max_positions": 7,
    },
    "NORMAL": {
        "size_multiplier": 1.0,
        "signal_threshold": 0.60,
        "stop_distance_multiplier": 1.0,
        "max_positions": 5,
    },
    "HIGH": {
        "size_multiplier": 0.5,
        "signal_threshold": 0.75,
        "stop_distance_multiplier": 1.5,
        "max_positions": 3,
    },
}

_MACRO_ADJUSTMENTS = {
    "EXPANSION": {"bias": 0.1, "note": "Bias towards long"},
    "CONTRACTION": {"bias": -0.1, "note": "Bias towards short/hedge"},
    "TRANSITION": {"bias": 0.0, "note": "Reduce exposure"},
}


class RegimeStrategyEngine:
    """
    Adapts trading strategy parameters based on market regime.

    Usage:
        engine = RegimeStrategyEngine()
        regime = engine.classify_regime(
            returns=recent_returns,
            volumes=recent_volumes,
            spreads=recent_spreads,
        )
        adaptation = engine.get_adaptation(regime)
    """

    def __init__(
        self,
        vol_lookback: int = 50,
        macro_lookback: int = 200,
        liquidity_lookback: int = 30,
    ) -> None:
        self._vol_lookback = vol_lookback
        self._macro_lookback = macro_lookback
        self._liq_lookback = liquidity_lookback

    def classify_regime(
        self,
        returns: np.ndarray,
        volumes: np.ndarray | None = None,
        spreads: np.ndarray | None = None,
    ) -> RegimeState:
        """
        Classify current market regime across all dimensions.

        Parameters
        ----------
        returns : array of recent returns
        volumes : array of recent volumes (optional)
        spreads : array of recent bid-ask spreads in bps (optional)
        """
        ts = datetime.now(timezone.utc).isoformat()

        # 1. Volatility regime
        vol_regime, vol_details = self._classify_volatility(returns)

        # 2. Macro regime
        macro_regime, macro_details = self._classify_macro(returns)

        # 3. Liquidity regime
        liq_regime, liq_details = self._classify_liquidity(volumes, spreads)

        # Confidence based on data availability
        n = len(returns)
        confidence = min(1.0, n / self._macro_lookback)

        details = {
            "volatility_details": vol_details,
            "macro_details": macro_details,
            "liquidity_details": liq_details,
        }

        state = RegimeState(
            timestamp=ts,
            volatility=vol_regime,
            macro=macro_regime,
            liquidity=liq_regime,
            confidence=confidence,
            details=details,
        )

        logger.info(
            "Regime classified: vol=%s macro=%s liq=%s (conf=%.2f)",
            vol_regime, macro_regime, liq_regime, confidence,
        )
        return state

    def get_adaptation(self, regime: RegimeState) -> RegimeAdaptation:
        """
        Get strategy adaptation parameters for current regime.
        """
        # Start with volatility adaptations
        vol_params = _VOL_ADAPTATIONS.get(
            regime.volatility, _VOL_ADAPTATIONS["NORMAL"],
        )

        adaptation = RegimeAdaptation(
            size_multiplier=vol_params["size_multiplier"],
            signal_threshold=vol_params["signal_threshold"],
            stop_distance_multiplier=vol_params["stop_distance_multiplier"],
            max_positions=vol_params["max_positions"],
        )

        # Apply macro adjustments
        macro_adj = _MACRO_ADJUSTMENTS.get(
            regime.macro, _MACRO_ADJUSTMENTS["TRANSITION"],
        )
        adaptation.notes.append(macro_adj["note"])

        if regime.macro == "CONTRACTION":
            adaptation.size_multiplier *= 0.7
            adaptation.signal_threshold += 0.05
            adaptation.disabled_signals.append("momentum_long")

        if regime.macro == "TRANSITION":
            adaptation.size_multiplier *= 0.8

        # Apply liquidity adjustments
        if regime.liquidity == "SCARCE":
            adaptation.size_multiplier *= 0.6
            adaptation.stop_distance_multiplier *= 1.3
            adaptation.max_positions = min(adaptation.max_positions, 3)
            adaptation.notes.append("Liquidity scarce — reduce size")

        elif regime.liquidity == "ABUNDANT":
            adaptation.size_multiplier *= 1.1
            adaptation.notes.append("Liquidity abundant")

        # Final bounds
        adaptation.size_multiplier = max(0.1, min(2.0, adaptation.size_multiplier))
        adaptation.signal_threshold = max(0.4, min(0.95, adaptation.signal_threshold))

        return adaptation

    def _classify_volatility(
        self, returns: np.ndarray,
    ) -> tuple[str, dict]:
        """Classify volatility regime using rolling realised vol."""
        n = len(returns)
        if n < 10:
            return "NORMAL", {"error": "insufficient_data"}

        lookback = min(n, self._vol_lookback)
        recent_vol = float(np.std(returns[-lookback:], ddof=1)) * np.sqrt(252)

        if n >= self._vol_lookback * 2:
            hist_vol = float(np.std(returns[:-lookback], ddof=1)) * np.sqrt(252)
        else:
            hist_vol = recent_vol

        vol_ratio = recent_vol / max(hist_vol, 1e-10)

        if vol_ratio < 0.7:
            regime = "LOW"
        elif vol_ratio > 1.5:
            regime = "HIGH"
        else:
            regime = "NORMAL"

        return regime, {
            "recent_vol": round(recent_vol, 4),
            "hist_vol": round(hist_vol, 4),
            "vol_ratio": round(vol_ratio, 4),
        }

    def _classify_macro(
        self, returns: np.ndarray,
    ) -> tuple[str, dict]:
        """Classify macro regime using cumulative return trend."""
        n = len(returns)
        if n < 20:
            return "TRANSITION", {"error": "insufficient_data"}

        lookback = min(n, self._macro_lookback)
        cum_return = float(np.sum(returns[-lookback:]))

        # Trend: rolling 50-bar vs 200-bar return
        short_window = min(50, n)
        long_window = min(200, n)
        short_ret = float(np.sum(returns[-short_window:]))
        long_ret = float(np.sum(returns[-long_window:]))

        if short_ret > 0 and long_ret > 0:
            regime = "EXPANSION"
        elif short_ret < 0 and long_ret < 0:
            regime = "CONTRACTION"
        else:
            regime = "TRANSITION"

        return regime, {
            "cum_return": round(cum_return, 4),
            "short_trend": round(short_ret, 4),
            "long_trend": round(long_ret, 4),
        }

    def _classify_liquidity(
        self,
        volumes: np.ndarray | None,
        spreads: np.ndarray | None,
    ) -> tuple[str, dict]:
        """Classify liquidity regime."""
        if volumes is None or len(volumes) < 10:
            return "NORMAL", {"error": "no_volume_data"}

        lookback = min(len(volumes), self._liq_lookback)
        recent_vol = float(np.mean(volumes[-lookback:]))

        if len(volumes) >= lookback * 2:
            hist_vol = float(np.mean(volumes[:-lookback]))
        else:
            hist_vol = recent_vol

        vol_ratio = recent_vol / max(hist_vol, 1e-10)

        # Also check spreads if available
        spread_score = 1.0
        if spreads is not None and len(spreads) >= 10:
            recent_spread = float(np.mean(spreads[-lookback:]))
            if len(spreads) >= lookback * 2:
                hist_spread = float(np.mean(spreads[:-lookback]))
            else:
                hist_spread = recent_spread
            spread_score = recent_spread / max(hist_spread, 1e-10)

        # Combined score: high volume + low spreads = abundant
        liq_score = vol_ratio / max(spread_score, 0.1)

        if liq_score > 1.3:
            regime = "ABUNDANT"
        elif liq_score < 0.7:
            regime = "SCARCE"
        else:
            regime = "NORMAL"

        return regime, {
            "volume_ratio": round(vol_ratio, 4),
            "spread_score": round(spread_score, 4),
            "liquidity_score": round(liq_score, 4),
        }
