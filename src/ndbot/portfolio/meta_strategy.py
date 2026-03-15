"""
Meta-Strategy Engine (Step 6).

Combines multiple trading signals into robust composite signals:

  Methods:
    1. Simple model averaging
    2. Confidence-weighted averaging
    3. Inverse-variance weighting
    4. Sharpe-weighted ensemble
    5. Rank-based combination
    6. Dynamic weight adaptation

  Features:
    - Signal decorrelation check
    - Diversity bonus for uncorrelated signals
    - Automatic weight rebalancing
    - Signal conflict detection
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SignalInput:
    """A single signal to combine."""

    name: str
    signal: float           # [-1, +1] directional signal
    confidence: float = 0.5  # [0, 1] confidence level
    sharpe: float = 0.0     # Historical Sharpe ratio
    correlation: float = 0.0  # Correlation with consensus


@dataclass
class MetaSignal:
    """Combined meta-strategy signal."""

    timestamp: str
    direction: float         # [-1, +1]
    strength: float          # [0, 1]
    confidence: float        # [0, 1]
    method: str
    n_signals: int
    agreement_ratio: float   # Fraction of signals agreeing on direction
    signal_weights: dict[str, float] = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "direction": round(self.direction, 4),
            "strength": round(self.strength, 4),
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "n_signals": self.n_signals,
            "agreement_ratio": round(self.agreement_ratio, 4),
            "signal_weights": {
                k: round(v, 4) for k, v in self.signal_weights.items()
            },
            "details": self.details,
        }


class MetaStrategyEngine:
    """
    Combines multiple signals into a robust meta-signal.

    Usage:
        engine = MetaStrategyEngine()
        signals = [
            SignalInput("logistic", 0.8, 0.7, 1.2),
            SignalInput("gbm", -0.3, 0.6, 0.9),
            SignalInput("news_sentiment", 0.5, 0.8, 1.0),
        ]
        meta = engine.combine(signals)
    """

    def __init__(
        self,
        method: str = "sharpe_weighted",
        min_agreement: float = 0.5,
        diversity_bonus: float = 0.1,
    ) -> None:
        self._method = method
        self._min_agreement = min_agreement
        self._diversity_bonus = diversity_bonus

        # Historical signal tracking for dynamic weights
        self._signal_history: dict[str, list[float]] = {}
        self._return_history: list[float] = []

    def combine(
        self,
        signals: list[SignalInput],
        method: str | None = None,
    ) -> MetaSignal:
        """
        Combine multiple signals into a meta-signal.

        Parameters
        ----------
        signals : list of SignalInput
        method : override default combination method
        """
        ts = datetime.now(timezone.utc).isoformat()
        method = method or self._method

        if not signals:
            return MetaSignal(
                timestamp=ts, direction=0.0, strength=0.0,
                confidence=0.0, method=method, n_signals=0,
                agreement_ratio=0.0,
            )

        # Compute agreement
        directions = [np.sign(s.signal) for s in signals]
        if directions:
            consensus_dir = np.sign(sum(directions))
            agreement = sum(
                1 for d in directions if d == consensus_dir
            ) / len(directions)
        else:
            consensus_dir = 0.0
            agreement = 0.0

        # Dispatch to method
        if method == "simple_average":
            direction, strength, weights = self._simple_average(signals)
        elif method == "confidence_weighted":
            direction, strength, weights = self._confidence_weighted(signals)
        elif method == "inverse_variance":
            direction, strength, weights = self._inverse_variance(signals)
        elif method == "sharpe_weighted":
            direction, strength, weights = self._sharpe_weighted(signals)
        elif method == "rank_based":
            direction, strength, weights = self._rank_based(signals)
        else:
            direction, strength, weights = self._sharpe_weighted(signals)

        # Confidence: combination of agreement and individual confidences
        avg_conf = float(np.mean([s.confidence for s in signals]))
        confidence = avg_conf * agreement

        # Diversity bonus: reward if signals are decorrelated
        if len(signals) >= 3:
            sigs = np.array([s.signal for s in signals])
            if np.std(sigs) > 0.1:
                confidence = min(1.0, confidence + self._diversity_bonus)

        # Apply minimum agreement filter
        if agreement < self._min_agreement:
            strength *= 0.5
            confidence *= 0.5

        return MetaSignal(
            timestamp=ts,
            direction=float(np.clip(direction, -1, 1)),
            strength=float(np.clip(strength, 0, 1)),
            confidence=float(np.clip(confidence, 0, 1)),
            method=method,
            n_signals=len(signals),
            agreement_ratio=float(agreement),
            signal_weights=weights,
        )

    def _simple_average(
        self, signals: list[SignalInput],
    ) -> tuple[float, float, dict[str, float]]:
        """Equal-weight average."""
        w = 1.0 / len(signals)
        direction = sum(s.signal * w for s in signals)
        strength = abs(direction)
        weights = {s.name: w for s in signals}
        return direction, strength, weights

    def _confidence_weighted(
        self, signals: list[SignalInput],
    ) -> tuple[float, float, dict[str, float]]:
        """Weight by confidence level."""
        total_conf = sum(s.confidence for s in signals)
        if total_conf <= 0:
            return self._simple_average(signals)

        weights: dict[str, float] = {}
        direction = 0.0
        for s in signals:
            w = s.confidence / total_conf
            weights[s.name] = w
            direction += s.signal * w

        return direction, abs(direction), weights

    def _inverse_variance(
        self, signals: list[SignalInput],
    ) -> tuple[float, float, dict[str, float]]:
        """Weight inversely by estimated variance (use confidence as proxy)."""
        # Higher confidence → lower variance → higher weight
        variances = [1.0 / max(s.confidence, 0.1) for s in signals]
        inv_vars = [1.0 / v for v in variances]
        total = sum(inv_vars)

        weights: dict[str, float] = {}
        direction = 0.0
        for s, iv in zip(signals, inv_vars):
            w = iv / total
            weights[s.name] = w
            direction += s.signal * w

        return direction, abs(direction), weights

    def _sharpe_weighted(
        self, signals: list[SignalInput],
    ) -> tuple[float, float, dict[str, float]]:
        """Weight by historical Sharpe ratio."""
        sharpes = [max(0.01, s.sharpe) for s in signals]
        total = sum(sharpes)

        weights: dict[str, float] = {}
        direction = 0.0
        for s, sh in zip(signals, sharpes):
            w = sh / total
            weights[s.name] = w
            direction += s.signal * w

        return direction, abs(direction), weights

    def _rank_based(
        self, signals: list[SignalInput],
    ) -> tuple[float, float, dict[str, float]]:
        """Rank-based combination (robust to outliers)."""
        ranked = sorted(signals, key=lambda s: s.sharpe, reverse=True)
        n = len(ranked)
        rank_weights = [(n - i) for i in range(n)]
        total = sum(rank_weights)

        weights: dict[str, float] = {}
        direction = 0.0
        for s, rw in zip(ranked, rank_weights):
            w = rw / total
            weights[s.name] = w
            direction += s.signal * w

        return direction, abs(direction), weights

    def update_history(
        self,
        signal_values: dict[str, float],
        realised_return: float,
    ) -> None:
        """Track signal history for dynamic weight adaptation."""
        for name, val in signal_values.items():
            if name not in self._signal_history:
                self._signal_history[name] = []
            self._signal_history[name].append(val)

        self._return_history.append(realised_return)

    def compute_dynamic_weights(self) -> dict[str, float]:
        """
        Compute adaptive weights based on recent signal performance.

        Returns weights proportional to each signal's rolling Sharpe.
        """
        if len(self._return_history) < 20:
            return {}

        weights: dict[str, float] = {}
        returns = np.array(self._return_history[-100:])

        for name, history in self._signal_history.items():
            if len(history) < 20:
                continue
            signal_arr = np.array(history[-100:])
            n = min(len(signal_arr), len(returns))
            signal_returns = np.sign(signal_arr[-n:]) * returns[-n:]

            std = float(np.std(signal_returns, ddof=1))
            if std > 0:
                sharpe = float(np.mean(signal_returns)) / std * np.sqrt(252)
                weights[name] = max(0, sharpe)
            else:
                weights[name] = 0.0

        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def detect_signal_conflict(
        self, signals: list[SignalInput],
    ) -> dict:
        """Check if signals are significantly conflicting."""
        if len(signals) < 2:
            return {"conflict": False, "severity": 0.0}

        directions = [np.sign(s.signal) for s in signals]
        n_long = sum(1 for d in directions if d > 0)
        n_short = sum(1 for d in directions if d < 0)
        total = n_long + n_short

        if total == 0:
            return {"conflict": False, "severity": 0.0}

        balance = abs(n_long - n_short) / total
        conflict = balance < 0.3

        return {
            "conflict": conflict,
            "severity": round(1.0 - balance, 4),
            "n_long": n_long,
            "n_short": n_short,
            "n_neutral": len(signals) - total,
        }
