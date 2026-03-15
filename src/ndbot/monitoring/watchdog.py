"""
Automated Failure Detection — System Watchdog (Step 10).

Continuously monitors the trading system for anomalies:

  1. Strategy drift      — performance deviating from expectations
  2. Data feed anomalies — gaps, spikes, stale data
  3. Unexpected drawdown — drawdown exceeding tolerated limits
  4. API instability     — connection failures, latency spikes
  5. Model degradation   — rolling Sharpe dropping below threshold

Triggers kill switch automatically when critical failures detected.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_DRIFT_THRESHOLD = 2.0       # Sharpe drop of 2.0 from baseline
DEFAULT_DRAWDOWN_LIMIT = 0.15       # 15% max drawdown
DEFAULT_FEED_TIMEOUT_SEC = 300      # 5 minutes no data = stale
DEFAULT_LATENCY_LIMIT_MS = 5000     # 5 seconds API latency
DEFAULT_ROLLING_WINDOW = 50         # Bars for rolling metrics


@dataclass
class WatchdogAlert:
    """A failure detection alert."""
    timestamp: str
    alert_type: str
    severity: str        # "warning", "critical"
    message: str
    details: dict = field(default_factory=dict)
    kill_switch_triggered: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "kill_switch_triggered": self.kill_switch_triggered,
        }


class SystemWatchdog:
    """
    Real-time system watchdog for automated failure detection.

    Usage:
        watchdog = SystemWatchdog(on_kill_switch=my_halt_function)
        # Feed it data continuously
        watchdog.record_return(0.001)
        watchdog.record_feed_heartbeat("rss_energy")
        watchdog.record_api_latency(50.0)
        # Check for problems
        alerts = watchdog.check_all()
    """

    def __init__(
        self,
        baseline_sharpe: float = 1.0,
        drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
        drawdown_limit: float = DEFAULT_DRAWDOWN_LIMIT,
        feed_timeout_sec: float = DEFAULT_FEED_TIMEOUT_SEC,
        latency_limit_ms: float = DEFAULT_LATENCY_LIMIT_MS,
        rolling_window: int = DEFAULT_ROLLING_WINDOW,
        on_kill_switch: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._baseline_sharpe = baseline_sharpe
        self._drift_threshold = drift_threshold
        self._dd_limit = drawdown_limit
        self._feed_timeout = feed_timeout_sec
        self._latency_limit = latency_limit_ms
        self._window = rolling_window
        self._on_kill_switch = on_kill_switch

        self._returns: deque[float] = deque(maxlen=rolling_window * 10)
        self._equity: list[float] = []
        self._peak_equity: float = 0.0
        self._feed_heartbeats: dict[str, float] = {}
        self._api_latencies: deque[float] = deque(maxlen=100)
        self._alerts: list[WatchdogAlert] = []
        self._kill_switch_active = False

    def record_return(self, ret: float) -> None:
        """Record a strategy return for drift detection."""
        self._returns.append(ret)
        if self._equity:
            new_eq = self._equity[-1] * (1 + ret)
        else:
            new_eq = 10000 * (1 + ret)
        self._equity.append(new_eq)
        self._peak_equity = max(self._peak_equity, new_eq)

    def record_feed_heartbeat(self, feed_name: str) -> None:
        """Record that a data feed is alive."""
        self._feed_heartbeats[feed_name] = time.monotonic()

    def record_api_latency(self, latency_ms: float) -> None:
        """Record an API call latency in milliseconds."""
        self._api_latencies.append(latency_ms)

    def check_all(self) -> list[WatchdogAlert]:
        """Run all failure detection checks. Returns new alerts."""
        new_alerts: list[WatchdogAlert] = []

        alert = self._check_strategy_drift()
        if alert:
            new_alerts.append(alert)

        alert = self._check_drawdown()
        if alert:
            new_alerts.append(alert)

        alerts = self._check_feed_health()
        new_alerts.extend(alerts)

        alert = self._check_api_stability()
        if alert:
            new_alerts.append(alert)

        alert = self._check_model_degradation()
        if alert:
            new_alerts.append(alert)

        self._alerts.extend(new_alerts)
        return new_alerts

    def _check_strategy_drift(self) -> Optional[WatchdogAlert]:
        """Detect if strategy performance is drifting from baseline."""
        if len(self._returns) < self._window:
            return None

        recent = np.array(list(self._returns)[-self._window:])
        rolling_sharpe = self._compute_sharpe(recent)
        drift = self._baseline_sharpe - rolling_sharpe

        if drift > self._drift_threshold:
            alert = WatchdogAlert(
                timestamp=datetime.now(timezone.utc).isoformat(),
                alert_type="strategy_drift",
                severity="critical",
                message=(
                    f"Strategy drift detected: rolling Sharpe={rolling_sharpe:.3f} "
                    f"vs baseline={self._baseline_sharpe:.3f}"
                ),
                details={
                    "rolling_sharpe": round(rolling_sharpe, 4),
                    "baseline_sharpe": self._baseline_sharpe,
                    "drift": round(drift, 4),
                },
            )
            if drift > self._drift_threshold * 1.5:
                self._trigger_kill_switch("strategy_drift")
                alert.kill_switch_triggered = True
            return alert
        return None

    def _check_drawdown(self) -> Optional[WatchdogAlert]:
        """Check if drawdown exceeds limit."""
        if not self._equity or self._peak_equity <= 0:
            return None

        current = self._equity[-1]
        dd = (self._peak_equity - current) / self._peak_equity

        if dd >= self._dd_limit:
            alert = WatchdogAlert(
                timestamp=datetime.now(timezone.utc).isoformat(),
                alert_type="excessive_drawdown",
                severity="critical",
                message=f"Drawdown {dd:.2%} exceeds limit {self._dd_limit:.2%}",
                details={
                    "current_drawdown": round(dd, 4),
                    "limit": self._dd_limit,
                    "peak_equity": round(self._peak_equity, 2),
                    "current_equity": round(current, 2),
                },
            )
            self._trigger_kill_switch("excessive_drawdown")
            alert.kill_switch_triggered = True
            return alert
        return None

    def _check_feed_health(self) -> list[WatchdogAlert]:
        """Check all feeds for staleness."""
        now = time.monotonic()
        alerts = []
        for feed, last_time in self._feed_heartbeats.items():
            gap = now - last_time
            if gap > self._feed_timeout:
                alerts.append(WatchdogAlert(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    alert_type="feed_stale",
                    severity="warning",
                    message=f"Feed '{feed}' stale for {gap:.0f}s",
                    details={"feed": feed, "gap_seconds": round(gap, 1)},
                ))
        return alerts

    def _check_api_stability(self) -> Optional[WatchdogAlert]:
        """Check API latency for instability."""
        if len(self._api_latencies) < 5:
            return None

        recent = list(self._api_latencies)[-10:]
        avg_latency = float(np.mean(recent))
        max_latency = float(np.max(recent))

        if max_latency > self._latency_limit:
            return WatchdogAlert(
                timestamp=datetime.now(timezone.utc).isoformat(),
                alert_type="api_instability",
                severity="warning",
                message=(
                    f"API latency spike: max={max_latency:.0f}ms "
                    f"avg={avg_latency:.0f}ms"
                ),
                details={
                    "max_latency_ms": round(max_latency, 1),
                    "avg_latency_ms": round(avg_latency, 1),
                    "limit_ms": self._latency_limit,
                },
            )
        return None

    def _check_model_degradation(self) -> Optional[WatchdogAlert]:
        """Check if model's rolling Sharpe has degraded significantly."""
        if len(self._returns) < self._window * 2:
            return None

        returns_arr = np.array(list(self._returns))
        first_half = returns_arr[:self._window]
        second_half = returns_arr[-self._window:]

        sharpe_first = self._compute_sharpe(first_half)
        sharpe_second = self._compute_sharpe(second_half)

        degradation = sharpe_first - sharpe_second
        if degradation > 1.5 and sharpe_second < 0.5:
            return WatchdogAlert(
                timestamp=datetime.now(timezone.utc).isoformat(),
                alert_type="model_degradation",
                severity="warning",
                message=(
                    f"Model degradation: Sharpe {sharpe_first:.3f} → "
                    f"{sharpe_second:.3f}"
                ),
                details={
                    "sharpe_early": round(sharpe_first, 4),
                    "sharpe_recent": round(sharpe_second, 4),
                    "degradation": round(degradation, 4),
                },
            )
        return None

    def _trigger_kill_switch(self, reason: str) -> None:
        """Activate the emergency kill switch."""
        if self._kill_switch_active:
            return
        self._kill_switch_active = True
        logger.critical("WATCHDOG KILL SWITCH: %s", reason)
        if self._on_kill_switch:
            self._on_kill_switch(reason)

    @staticmethod
    def _compute_sharpe(
        returns: np.ndarray, ann_factor: float = 252.0,
    ) -> float:
        if len(returns) < 2:
            return 0.0
        std = float(np.std(returns, ddof=1))
        if std == 0:
            return 0.0
        return float(np.mean(returns)) / std * np.sqrt(ann_factor)

    @property
    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def alerts(self) -> list[dict]:
        return [a.to_dict() for a in self._alerts]

    @property
    def stats(self) -> dict:
        return {
            "total_returns": len(self._returns),
            "total_alerts": len(self._alerts),
            "kill_switch": self._kill_switch_active,
            "feeds_tracked": len(self._feed_heartbeats),
            "peak_equity": round(self._peak_equity, 2),
        }
