"""
Edge Decay Monitoring (Step 9).

Monitors signal performance over time and detects alpha decay:

  Metrics:
    1. Rolling Sharpe decay — does Sharpe degrade over time?
    2. Signal half-life — how long before signal loses 50% of edge?
    3. Crowding indicator — increasing correlation with market
    4. Hit rate decay — declining accuracy
    5. Return attribution — shrinking alpha component

  Actions:
    - Warning when edge decays below threshold
    - Automatic signal deactivation at critical decay
    - Recommendation for signal refresh or retirement
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class EdgeDecayReport:
    """Edge decay analysis for a single signal."""

    signal_id: str
    timestamp: str
    current_sharpe: float = 0.0
    peak_sharpe: float = 0.0
    decay_pct: float = 0.0          # How much edge has decayed (0-100%)
    half_life_bars: int = -1         # Estimated half-life (-1 = not computed)
    crowding_score: float = 0.0      # [0, 1] how crowded the signal is
    hit_rate_trend: float = 0.0      # Slope of rolling hit rate
    status: str = "active"           # "active", "warning", "critical", "dead"
    recommendation: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "timestamp": self.timestamp,
            "current_sharpe": round(self.current_sharpe, 4),
            "peak_sharpe": round(self.peak_sharpe, 4),
            "decay_pct": round(self.decay_pct, 2),
            "half_life_bars": self.half_life_bars,
            "crowding_score": round(self.crowding_score, 4),
            "hit_rate_trend": round(self.hit_rate_trend, 6),
            "status": self.status,
            "recommendation": self.recommendation,
            "details": self.details,
        }


class EdgeDecayMonitor:
    """
    Monitors and detects edge decay in trading signals.

    Usage:
        monitor = EdgeDecayMonitor()
        report = monitor.analyse(
            signal_id="momentum_1h",
            signal_returns=returns_array,
            market_returns=market_array,
        )
    """

    def __init__(
        self,
        rolling_window: int = 60,
        warning_decay_pct: float = 40.0,
        critical_decay_pct: float = 70.0,
        min_sharpe: float = 0.3,
    ) -> None:
        self._window = rolling_window
        self._warn_decay = warning_decay_pct
        self._crit_decay = critical_decay_pct
        self._min_sharpe = min_sharpe

        # Track signals over time
        self._signal_data: dict[str, dict] = {}

    def analyse(
        self,
        signal_id: str,
        signal_returns: np.ndarray,
        market_returns: np.ndarray | None = None,
    ) -> EdgeDecayReport:
        """
        Analyse edge decay for a signal.

        Parameters
        ----------
        signal_returns : array of returns when signal is active
        market_returns : array of corresponding market returns
        """
        ts = datetime.now(timezone.utc).isoformat()
        n = len(signal_returns)

        if n < self._window:
            return EdgeDecayReport(
                signal_id=signal_id,
                timestamp=ts,
                status="insufficient_data",
                recommendation="Need more data",
                details={"n_observations": n, "min_required": self._window},
            )

        # 1. Rolling Sharpe
        rolling_sharpes = self._rolling_sharpe(signal_returns)
        current_sharpe = rolling_sharpes[-1] if len(rolling_sharpes) > 0 else 0.0
        peak_sharpe = float(np.max(rolling_sharpes)) if len(rolling_sharpes) > 0 else 0.0

        # Decay percentage
        if peak_sharpe > 0:
            decay_pct = max(0, (1 - current_sharpe / peak_sharpe) * 100)
        else:
            decay_pct = 100.0

        # 2. Half-life estimate
        half_life = self._estimate_half_life(rolling_sharpes, peak_sharpe)

        # 3. Crowding score
        crowding = 0.0
        if market_returns is not None and len(market_returns) >= self._window:
            crowding = self._compute_crowding(signal_returns, market_returns)

        # 4. Hit rate trend
        hit_rate_trend = self._hit_rate_trend(signal_returns)

        # 5. Determine status
        if current_sharpe < 0:
            status = "dead"
            recommendation = "Deactivate signal immediately"
        elif decay_pct >= self._crit_decay:
            status = "critical"
            recommendation = "Signal edge nearly exhausted — retire or refresh"
        elif decay_pct >= self._warn_decay:
            status = "warning"
            recommendation = "Edge decaying — monitor closely"
        elif current_sharpe < self._min_sharpe:
            status = "warning"
            recommendation = f"Sharpe below minimum ({self._min_sharpe})"
        else:
            status = "active"
            recommendation = "Signal performing within expectations"

        report = EdgeDecayReport(
            signal_id=signal_id,
            timestamp=ts,
            current_sharpe=current_sharpe,
            peak_sharpe=peak_sharpe,
            decay_pct=decay_pct,
            half_life_bars=half_life,
            crowding_score=crowding,
            hit_rate_trend=hit_rate_trend,
            status=status,
            recommendation=recommendation,
            details={
                "n_observations": n,
                "rolling_sharpe_last5": [
                    round(s, 4) for s in rolling_sharpes[-5:]
                ],
                "window": self._window,
            },
        )

        # Store for tracking
        self._signal_data[signal_id] = {
            "last_report": report.to_dict(),
            "last_sharpe": current_sharpe,
        }

        logger.info(
            "Edge decay [%s]: Sharpe=%.3f peak=%.3f decay=%.1f%% status=%s",
            signal_id, current_sharpe, peak_sharpe, decay_pct, status,
        )
        return report

    def _rolling_sharpe(self, returns: np.ndarray) -> np.ndarray:
        """Compute rolling Sharpe ratio."""
        n = len(returns)
        sharpes = []
        for i in range(self._window, n + 1):
            window = returns[i - self._window: i]
            std = float(np.std(window, ddof=1))
            if std > 0:
                sharpes.append(float(np.mean(window)) / std * np.sqrt(252))
            else:
                sharpes.append(0.0)
        return np.array(sharpes)

    def _estimate_half_life(
        self,
        rolling_sharpes: np.ndarray,
        peak_sharpe: float,
    ) -> int:
        """
        Estimate edge half-life in bars.

        Fits exponential decay to rolling Sharpe and estimates
        how many bars until signal reaches 50% of peak.
        """
        if len(rolling_sharpes) < 5 or peak_sharpe <= 0:
            return -1

        # Find peak position
        peak_idx = int(np.argmax(rolling_sharpes))
        post_peak = rolling_sharpes[peak_idx:]

        if len(post_peak) < 3:
            return -1

        # Fit linear trend to log(Sharpe) after peak
        positive = post_peak[post_peak > 0]
        if len(positive) < 3:
            return len(post_peak)  # Already decayed

        log_sharpe = np.log(positive)
        x = np.arange(len(positive))

        # Linear regression
        if np.std(x) > 0:
            slope = float(np.polyfit(x, log_sharpe, 1)[0])
        else:
            return -1

        if slope >= 0:
            return -1  # Not decaying

        # Half-life: t where exp(slope * t) = 0.5
        # slope * t = ln(0.5)
        half_life = int(abs(np.log(0.5) / slope))
        return max(1, half_life)

    def _compute_crowding(
        self,
        signal_returns: np.ndarray,
        market_returns: np.ndarray,
    ) -> float:
        """
        Estimate signal crowding.

        High correlation with market → signal is crowded.
        Increasing correlation over time → signal getting crowded.
        """
        n = min(len(signal_returns), len(market_returns))
        if n < self._window:
            return 0.0

        sr = signal_returns[-n:]
        mr = market_returns[-n:]

        # Rolling correlation
        half = n // 2
        corr_early = float(np.corrcoef(sr[:half], mr[:half])[0, 1])
        corr_late = float(np.corrcoef(sr[half:], mr[half:])[0, 1])

        # Crowding = absolute correlation (high = crowded)
        base_crowding = abs(corr_late)

        # Increasing correlation = getting more crowded
        if abs(corr_late) > abs(corr_early) + 0.1:
            base_crowding = min(1.0, base_crowding + 0.2)

        return float(np.clip(base_crowding, 0, 1))

    def _hit_rate_trend(self, returns: np.ndarray) -> float:
        """Compute trend of rolling hit rate."""
        if len(returns) < self._window * 2:
            return 0.0

        hit_rates = []
        for i in range(self._window, len(returns) + 1):
            window = returns[i - self._window: i]
            hit_rates.append(float(np.mean(window > 0)))

        if len(hit_rates) < 3:
            return 0.0

        x = np.arange(len(hit_rates))
        slope = float(np.polyfit(x, hit_rates, 1)[0])
        return slope

    def get_all_statuses(self) -> dict[str, str]:
        """Get status of all tracked signals."""
        return {
            sid: data.get("last_report", {}).get("status", "unknown")
            for sid, data in self._signal_data.items()
        }

    def should_deactivate(self, signal_id: str) -> bool:
        """Check if a signal should be automatically deactivated."""
        data = self._signal_data.get(signal_id)
        if not data:
            return False
        status = data.get("last_report", {}).get("status", "active")
        return status in ("dead", "critical")
