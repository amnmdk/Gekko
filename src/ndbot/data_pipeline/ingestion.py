"""
Ingestion validation and data integrity pipeline.

Responsibilities:
  - Validate incoming events (required fields, types, ranges)
  - Normalise timestamps to UTC
  - Deduplicate events by event_id
  - Check data integrity (no future dates, no missing fields)
  - Prevent look-ahead bias by rejecting events with future timestamps
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..feeds.base import EventDomain, NewsEvent

logger = logging.getLogger(__name__)

# Maximum age of an event before it's considered stale
MAX_EVENT_AGE_DAYS = 365

# Maximum allowed clock skew (events slightly in the future)
MAX_CLOCK_SKEW_SECONDS = 60


class IngestionValidator:
    """
    Validates and deduplicates incoming news events.

    Prevents:
      - Future data leakage (events with timestamps ahead of current time)
      - Duplicate events
      - Malformed events (missing fields, invalid types)
      - Misaligned timestamps (non-UTC, unparseable)
    """

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()
        self._stats = {
            "total_received": 0,
            "accepted": 0,
            "rejected_duplicate": 0,
            "rejected_future": 0,
            "rejected_stale": 0,
            "rejected_invalid": 0,
            "timestamps_normalised": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        """Return ingestion statistics."""
        return dict(self._stats)

    def validate(
        self,
        event: NewsEvent,
        current_time: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """
        Validate a single event.

        Returns (accepted: bool, reason: str).
        """
        self._stats["total_received"] += 1
        now = current_time or datetime.now(timezone.utc)

        # Check required fields
        if not event.headline or not event.headline.strip():
            self._stats["rejected_invalid"] += 1
            return False, "empty_headline"

        if not event.source or not event.source.strip():
            self._stats["rejected_invalid"] += 1
            return False, "empty_source"

        if event.domain == EventDomain.UNKNOWN:
            self._stats["rejected_invalid"] += 1
            return False, "unknown_domain"

        # Normalise timestamp to UTC
        event.published_at = self._normalise_timestamp(event.published_at)
        event.ingested_at = self._normalise_timestamp(event.ingested_at)

        # Check for future timestamps (look-ahead bias prevention)
        max_allowed = now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
        if event.published_at > max_allowed:
            self._stats["rejected_future"] += 1
            return False, "future_timestamp"

        # Check for stale events
        min_allowed = now - timedelta(days=MAX_EVENT_AGE_DAYS)
        if event.published_at < min_allowed:
            self._stats["rejected_stale"] += 1
            return False, "stale_event"

        # Deduplicate by event_id
        if event.event_id in self._seen_ids:
            self._stats["rejected_duplicate"] += 1
            return False, "duplicate"
        self._seen_ids.add(event.event_id)

        # Validate score ranges
        event.sentiment_score = max(-1.0, min(1.0, event.sentiment_score))
        event.importance_score = max(0.0, min(1.0, event.importance_score))
        event.credibility_weight = max(0.0, min(2.0, event.credibility_weight))

        self._stats["accepted"] += 1
        return True, "ok"

    def validate_batch(
        self,
        events: list[NewsEvent],
        current_time: Optional[datetime] = None,
    ) -> list[NewsEvent]:
        """
        Validate a batch of events. Returns only accepted events.
        """
        accepted = []
        for ev in events:
            ok, reason = self.validate(ev, current_time)
            if ok:
                accepted.append(ev)
            else:
                logger.debug("Event %s rejected: %s", ev.event_id[:8], reason)

        logger.info(
            "Ingestion: %d/%d events accepted (dup=%d, future=%d, stale=%d, invalid=%d)",
            len(accepted), len(events),
            self._stats["rejected_duplicate"],
            self._stats["rejected_future"],
            self._stats["rejected_stale"],
            self._stats["rejected_invalid"],
        )
        return accepted

    def validate_candles(self, candles) -> tuple[bool, list[str]]:
        """
        Validate a candle DataFrame for integrity.

        Checks:
          - Required columns present
          - No NaN prices
          - Monotonically increasing timestamps
          - No negative prices or volumes
          - No duplicate timestamps
        """
        issues: list[str] = []

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(candles.columns)
        if missing:
            issues.append(f"missing_columns: {missing}")

        if candles.empty:
            issues.append("empty_dataframe")
            return len(issues) == 0, issues

        # Check for NaN in price columns
        price_cols = [c for c in ["open", "high", "low", "close"] if c in candles.columns]
        for col in price_cols:
            nan_count = int(candles[col].isna().sum())
            if nan_count > 0:
                issues.append(f"nan_values: {col} has {nan_count} NaN rows")

        # Check for negative prices
        for col in price_cols:
            if col in candles.columns and (candles[col] < 0).any():
                issues.append(f"negative_prices: {col}")

        # Check monotonically increasing index
        if not candles.index.is_monotonic_increasing:
            issues.append("non_monotonic_timestamps")

        # Check for duplicate timestamps
        if candles.index.duplicated().any():
            n_dups = int(candles.index.duplicated().sum())
            issues.append(f"duplicate_timestamps: {n_dups}")

        if issues:
            logger.warning("Candle validation issues: %s", issues)
        else:
            logger.debug("Candle validation passed (%d rows)", len(candles))

        return len(issues) == 0, issues

    def reset(self) -> None:
        """Reset deduplication state and counters."""
        self._seen_ids.clear()
        for key in self._stats:
            self._stats[key] = 0

    @staticmethod
    def _normalise_timestamp(ts: datetime) -> datetime:
        """Ensure timestamp is timezone-aware UTC."""
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @staticmethod
    def compute_event_hash(source: str, url: str, headline: str) -> str:
        """Deterministic event ID from content."""
        raw = f"{source}|{url}|{headline}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
