"""
System monitoring and alerting.

Features:
  - Real-time system health tracking
  - Strategy performance monitoring
  - Alerts when:
    - Drawdown exceeds threshold
    - Data feed fails
    - Exchange connection drops
    - Daily loss limit approached
  - Structured event logging with timestamp + component
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Default alert thresholds
DEFAULT_DRAWDOWN_WARN_PCT = 0.08
DEFAULT_DRAWDOWN_CRITICAL_PCT = 0.12
DEFAULT_DAILY_LOSS_WARN_PCT = 0.03
DEFAULT_FEED_TIMEOUT_SECONDS = 300
MAX_ALERT_HISTORY = 500


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """A single monitoring alert."""
    timestamp: datetime
    level: AlertLevel
    component: str
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "component": self.component,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class HealthStatus:
    """System health snapshot."""
    timestamp: datetime
    overall: str  # "healthy", "degraded", "critical"
    components: dict[str, str]
    active_alerts: int
    uptime_seconds: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall": self.overall,
            "components": self.components,
            "active_alerts": self.active_alerts,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


class SystemMonitor:
    """
    Central monitoring hub for the trading system.

    Tracks:
      - Component health (feeds, exchange, strategy, portfolio)
      - Performance metrics (drawdown, daily PnL)
      - System metrics (uptime, event counts)

    Emits alerts when thresholds are breached.
    """

    def __init__(
        self,
        drawdown_warn_pct: float = DEFAULT_DRAWDOWN_WARN_PCT,
        drawdown_critical_pct: float = DEFAULT_DRAWDOWN_CRITICAL_PCT,
        daily_loss_warn_pct: float = DEFAULT_DAILY_LOSS_WARN_PCT,
        feed_timeout_seconds: float = DEFAULT_FEED_TIMEOUT_SECONDS,
        on_alert: Optional[Callable[[Alert], None]] = None,
    ) -> None:
        self._dd_warn = drawdown_warn_pct
        self._dd_critical = drawdown_critical_pct
        self._daily_warn = daily_loss_warn_pct
        self._feed_timeout = feed_timeout_seconds
        self._on_alert = on_alert

        self._start_time = time.monotonic()
        self._alerts: deque[Alert] = deque(maxlen=MAX_ALERT_HISTORY)
        self._component_status: dict[str, str] = {}
        self._last_feed_time: dict[str, float] = {}
        self._event_counts: dict[str, int] = {}
        self._kill_switch_active = False

    @property
    def kill_switch_active(self) -> bool:
        """Whether the emergency kill switch has been triggered."""
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str) -> None:
        """Activate the emergency kill switch."""
        self._kill_switch_active = True
        self._emit_alert(
            AlertLevel.CRITICAL, "kill_switch",
            f"KILL SWITCH ACTIVATED: {reason}",
        )

    def deactivate_kill_switch(self) -> None:
        """Manually deactivate the kill switch."""
        self._kill_switch_active = False
        self._emit_alert(
            AlertLevel.INFO, "kill_switch",
            "Kill switch deactivated manually",
        )

    def check_drawdown(self, current_drawdown_pct: float) -> None:
        """Check drawdown against thresholds."""
        if current_drawdown_pct >= self._dd_critical:
            self._emit_alert(
                AlertLevel.CRITICAL, "portfolio",
                f"Drawdown critical: {current_drawdown_pct:.2%}",
                {"drawdown_pct": current_drawdown_pct, "threshold": self._dd_critical},
            )
            self.activate_kill_switch(
                f"drawdown={current_drawdown_pct:.2%} >= {self._dd_critical:.2%}"
            )
        elif current_drawdown_pct >= self._dd_warn:
            self._emit_alert(
                AlertLevel.WARNING, "portfolio",
                f"Drawdown warning: {current_drawdown_pct:.2%}",
                {"drawdown_pct": current_drawdown_pct, "threshold": self._dd_warn},
            )

    def check_daily_loss(self, daily_loss_pct: float) -> None:
        """Check daily loss against threshold."""
        if daily_loss_pct >= self._daily_warn:
            self._emit_alert(
                AlertLevel.WARNING, "portfolio",
                f"Daily loss warning: {daily_loss_pct:.2%}",
                {"daily_loss_pct": daily_loss_pct},
            )

    def record_feed_activity(self, feed_name: str) -> None:
        """Record that a feed has successfully delivered data."""
        self._last_feed_time[feed_name] = time.monotonic()
        self._component_status[f"feed:{feed_name}"] = "healthy"
        self._event_counts[feed_name] = self._event_counts.get(feed_name, 0) + 1

    def check_feed_health(self) -> list[str]:
        """Check all feeds for staleness. Returns list of stale feeds."""
        now = time.monotonic()
        stale = []
        for name, last_time in self._last_feed_time.items():
            if now - last_time > self._feed_timeout:
                stale.append(name)
                self._component_status[f"feed:{name}"] = "stale"
                self._emit_alert(
                    AlertLevel.WARNING, f"feed:{name}",
                    f"Feed {name} has not delivered data for {now - last_time:.0f}s",
                )
        return stale

    def record_exchange_status(self, connected: bool, exchange_id: str = "exchange") -> None:
        """Record exchange connection status."""
        status = "healthy" if connected else "disconnected"
        self._component_status[f"exchange:{exchange_id}"] = status
        if not connected:
            self._emit_alert(
                AlertLevel.CRITICAL, f"exchange:{exchange_id}",
                f"Exchange connection lost: {exchange_id}",
            )

    def record_component_status(self, component: str, status: str) -> None:
        """Record arbitrary component status."""
        self._component_status[component] = status

    def get_health(self) -> HealthStatus:
        """Get current system health snapshot."""
        now = datetime.now(timezone.utc)
        uptime = time.monotonic() - self._start_time

        # Determine overall health
        statuses = set(self._component_status.values())
        if "disconnected" in statuses or self._kill_switch_active:
            overall = "critical"
        elif "stale" in statuses or "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        active_alerts = sum(
            1 for a in self._alerts
            if a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL)
        )

        return HealthStatus(
            timestamp=now,
            overall=overall,
            components=dict(self._component_status),
            active_alerts=active_alerts,
            uptime_seconds=uptime,
        )

    def get_alerts(self, limit: int = 50, level: Optional[AlertLevel] = None) -> list[dict]:
        """Get recent alerts, optionally filtered by level."""
        alerts = list(self._alerts)
        if level:
            alerts = [a for a in alerts if a.level == level]
        return [a.to_dict() for a in alerts[-limit:]]

    def get_event_counts(self) -> dict[str, int]:
        """Get event counts per feed/source."""
        return dict(self._event_counts)

    def _emit_alert(
        self,
        level: AlertLevel,
        component: str,
        message: str,
        details: Optional[dict] = None,
    ) -> None:
        """Create and store an alert."""
        alert = Alert(
            timestamp=datetime.now(timezone.utc),
            level=level,
            component=component,
            message=message,
            details=details or {},
        )
        self._alerts.append(alert)

        # Log the alert
        log_fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }[level]
        log_fn("[ALERT:%s] %s — %s", level.value, component, message)

        # Call external handler if registered
        if self._on_alert:
            self._on_alert(alert)
