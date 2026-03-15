"""
Point-in-Time Data Validation (Step 1).

Ensures backtests never access data that was not available at decision time.

Features:
  - Timestamp validation with configurable release lag
  - News release lag modelling (API latency, processing delay)
  - Data availability window enforcement
  - Point-in-time dataset snapshot creation
  - Look-ahead bias detection and prevention
  - Forward data leakage guards

Every piece of data (candle, event, feature) carries a
`known_at` timestamp. No model or signal may observe data
where `known_at > decision_time`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default release lag assumptions
DEFAULT_NEWS_LAG_SECONDS = 30       # API ingestion latency
DEFAULT_CANDLE_LAG_SECONDS = 5      # Exchange candle publication delay
DEFAULT_FEATURE_LAG_SECONDS = 60    # Feature computation pipeline delay


@dataclass
class DataRecord:
    """A single data point with availability metadata."""
    data_id: str
    data_type: str           # "candle", "event", "feature", "price"
    event_time: datetime     # When the real-world event occurred
    known_at: datetime       # When the system could first observe it
    payload: dict = field(default_factory=dict)

    def available_at(self, decision_time: datetime) -> bool:
        """Whether this data was available at decision time."""
        return self.known_at <= decision_time


@dataclass
class ReleaseLagConfig:
    """Configurable release lag per data type."""
    news_lag_seconds: float = DEFAULT_NEWS_LAG_SECONDS
    candle_lag_seconds: float = DEFAULT_CANDLE_LAG_SECONDS
    feature_lag_seconds: float = DEFAULT_FEATURE_LAG_SECONDS
    custom_lags: dict[str, float] = field(default_factory=dict)

    def get_lag(self, data_type: str) -> timedelta:
        """Get the release lag for a data type."""
        if data_type in self.custom_lags:
            return timedelta(seconds=self.custom_lags[data_type])
        mapping = {
            "event": self.news_lag_seconds,
            "news": self.news_lag_seconds,
            "candle": self.candle_lag_seconds,
            "feature": self.feature_lag_seconds,
        }
        secs = mapping.get(data_type, 0)
        return timedelta(seconds=secs)


class PointInTimeValidator:
    """
    Enforces point-in-time correctness across all data access.

    Usage:
        validator = PointInTimeValidator()
        # Register data as it becomes available
        validator.register("candle_123", "candle", event_time, candle_data)
        # Query what's available at a decision point
        available = validator.query("candle", decision_time)
    """

    def __init__(
        self,
        lag_config: Optional[ReleaseLagConfig] = None,
    ) -> None:
        self._lag_config = lag_config or ReleaseLagConfig()
        self._records: list[DataRecord] = []
        self._violations: list[dict] = []
        self._stats = {
            "total_registered": 0,
            "total_queries": 0,
            "violations_detected": 0,
            "records_filtered": 0,
        }

    def register(
        self,
        data_id: str,
        data_type: str,
        event_time: datetime,
        payload: Optional[dict] = None,
        known_at: Optional[datetime] = None,
    ) -> DataRecord:
        """
        Register a data point with its availability timestamp.

        If known_at is not provided, it is computed as:
          known_at = event_time + release_lag(data_type)
        """
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        if known_at is None:
            lag = self._lag_config.get_lag(data_type)
            known_at = event_time + lag
        elif known_at.tzinfo is None:
            known_at = known_at.replace(tzinfo=timezone.utc)

        record = DataRecord(
            data_id=data_id,
            data_type=data_type,
            event_time=event_time,
            known_at=known_at,
            payload=payload or {},
        )
        self._records.append(record)
        self._stats["total_registered"] += 1
        return record

    def query(
        self,
        data_type: str,
        decision_time: datetime,
    ) -> list[DataRecord]:
        """
        Return all records of data_type available at decision_time.

        This is the core look-ahead bias prevention mechanism:
        only data with known_at <= decision_time is returned.
        """
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=timezone.utc)

        self._stats["total_queries"] += 1
        available = []
        for r in self._records:
            if r.data_type == data_type and r.available_at(decision_time):
                available.append(r)
            elif (r.data_type == data_type
                  and r.event_time <= decision_time
                  and not r.available_at(decision_time)):
                self._stats["records_filtered"] += 1

        return available

    def check_access(
        self,
        data_id: str,
        data_type: str,
        event_time: datetime,
        access_time: datetime,
    ) -> tuple[bool, str]:
        """
        Check if accessing a data point at access_time is valid.

        Returns (is_valid, reason).
        """
        if access_time.tzinfo is None:
            access_time = access_time.replace(tzinfo=timezone.utc)
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)

        lag = self._lag_config.get_lag(data_type)
        known_at = event_time + lag

        if access_time < known_at:
            violation = {
                "data_id": data_id,
                "data_type": data_type,
                "event_time": event_time.isoformat(),
                "known_at": known_at.isoformat(),
                "access_time": access_time.isoformat(),
                "lag_seconds": lag.total_seconds(),
                "violation": "look_ahead_bias",
            }
            self._violations.append(violation)
            self._stats["violations_detected"] += 1
            return False, "look_ahead_bias"

        if access_time < event_time:
            violation = {
                "data_id": data_id,
                "data_type": data_type,
                "event_time": event_time.isoformat(),
                "access_time": access_time.isoformat(),
                "violation": "future_data_access",
            }
            self._violations.append(violation)
            self._stats["violations_detected"] += 1
            return False, "future_data_access"

        return True, "ok"

    def validate_candle_access(
        self,
        candles: pd.DataFrame,
        decision_time: datetime,
    ) -> pd.DataFrame:
        """
        Filter a candle DataFrame to only include bars available
        at decision_time (respecting candle close + lag).
        """
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=timezone.utc)

        lag = self._lag_config.get_lag("candle")
        cutoff = decision_time - lag

        # Only candles whose close time <= cutoff are available
        valid = candles[candles.index <= cutoff]
        n_filtered = len(candles) - len(valid)
        if n_filtered > 0:
            self._stats["records_filtered"] += n_filtered
            logger.debug(
                "PIT: filtered %d future candles at decision=%s",
                n_filtered, decision_time.isoformat(),
            )
        return valid

    def create_snapshot(
        self,
        decision_time: datetime,
        output_dir: str = "data/pit_snapshots",
    ) -> Path:
        """
        Create a point-in-time snapshot of all available data
        at the given decision_time.
        """
        if decision_time.tzinfo is None:
            decision_time = decision_time.replace(tzinfo=timezone.utc)

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        available = [
            r for r in self._records
            if r.available_at(decision_time)
        ]

        snapshot = {
            "decision_time": decision_time.isoformat(),
            "n_records": len(available),
            "by_type": {},
            "records": [],
        }

        for r in available:
            snapshot["records"].append({
                "data_id": r.data_id,
                "data_type": r.data_type,
                "event_time": r.event_time.isoformat(),
                "known_at": r.known_at.isoformat(),
            })
            snapshot["by_type"][r.data_type] = (
                snapshot["by_type"].get(r.data_type, 0) + 1
            )

        ts_str = decision_time.strftime("%Y%m%d_%H%M%S")
        path = out / f"pit_snapshot_{ts_str}.json"
        with open(path, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)

        logger.info(
            "PIT snapshot: %d records at %s → %s",
            len(available), decision_time.isoformat(), path,
        )
        return path

    @property
    def violations(self) -> list[dict]:
        return list(self._violations)

    @property
    def stats(self) -> dict:
        return dict(self._stats)
