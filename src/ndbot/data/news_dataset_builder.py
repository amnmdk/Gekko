"""
Historical news dataset builder.

Builds and maintains a structured dataset of market-moving events from
multiple sources: RSS feeds, news APIs, financial social media, macro
calendar.

Each event record stores:
  - timestamp (UTC)
  - source
  - headline
  - event_type (from taxonomy)
  - affected_assets
  - sentiment_score
  - confidence_score

Dataset is stored in data/news_dataset/ as JSON-lines files
partitioned by date for efficient querying.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..feeds.base import NewsEvent

logger = logging.getLogger(__name__)

# Default dataset storage path
DEFAULT_DATASET_DIR = "data/news_dataset"


class DatasetRecord:
    """A single record in the news dataset."""

    __slots__ = (
        "event_id", "timestamp", "source", "headline",
        "summary", "event_type", "domain", "affected_assets",
        "sentiment_score", "confidence_score", "importance_score",
        "keywords", "entities", "url", "credibility_weight",
    )

    def __init__(
        self,
        event_id: str,
        timestamp: str,
        source: str,
        headline: str,
        summary: str = "",
        event_type: str = "UNKNOWN",
        domain: str = "UNKNOWN",
        affected_assets: Optional[list[str]] = None,
        sentiment_score: float = 0.0,
        confidence_score: float = 0.5,
        importance_score: float = 0.5,
        keywords: Optional[list[str]] = None,
        entities: Optional[dict] = None,
        url: str = "",
        credibility_weight: float = 1.0,
    ):
        self.event_id = event_id
        self.timestamp = timestamp
        self.source = source
        self.headline = headline
        self.summary = summary
        self.event_type = event_type
        self.domain = domain
        self.affected_assets = affected_assets or []
        self.sentiment_score = sentiment_score
        self.confidence_score = confidence_score
        self.importance_score = importance_score
        self.keywords = keywords or []
        self.entities = entities or {}
        self.url = url
        self.credibility_weight = credibility_weight

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "headline": self.headline,
            "summary": self.summary,
            "event_type": self.event_type,
            "domain": self.domain,
            "affected_assets": self.affected_assets,
            "sentiment_score": self.sentiment_score,
            "confidence_score": self.confidence_score,
            "importance_score": self.importance_score,
            "keywords": self.keywords,
            "entities": self.entities,
            "url": self.url,
            "credibility_weight": self.credibility_weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetRecord":
        return cls(**{
            k: d[k] for k in cls.__slots__ if k in d
        })

    @classmethod
    def from_news_event(
        cls,
        event: NewsEvent,
        event_type: str = "UNKNOWN",
        confidence_score: float = 0.5,
        affected_assets: Optional[list[str]] = None,
    ) -> "DatasetRecord":
        """Convert a NewsEvent to a DatasetRecord."""
        return cls(
            event_id=event.event_id,
            timestamp=event.published_at.isoformat(),
            source=event.source,
            headline=event.headline,
            summary=event.summary,
            event_type=event_type,
            domain=event.domain.value,
            affected_assets=affected_assets or [],
            sentiment_score=event.sentiment_score,
            confidence_score=confidence_score,
            importance_score=event.importance_score,
            keywords=event.keywords_matched,
            entities=event.entities,
            url=event.url,
            credibility_weight=event.credibility_weight,
        )


class NewsDatasetBuilder:
    """
    Builds and queries a historical news event dataset.

    Storage format: JSON-lines files partitioned by date.
    Path: data/news_dataset/YYYY/MM/DD.jsonl

    Usage:
        builder = NewsDatasetBuilder()
        builder.add_event(record)
        events = builder.query(domain="ENERGY_GEO", limit=100)
    """

    def __init__(self, dataset_dir: str = DEFAULT_DATASET_DIR):
        self._dir = Path(dataset_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._seen_ids: set[str] = set()
        self._stats = {
            "total_added": 0,
            "duplicates_skipped": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def add_event(self, record: DatasetRecord) -> bool:
        """
        Add a single event to the dataset.
        Returns True if added, False if duplicate.
        """
        if record.event_id in self._seen_ids:
            self._stats["duplicates_skipped"] += 1
            return False
        self._seen_ids.add(record.event_id)

        # Parse date for partitioning
        try:
            dt = datetime.fromisoformat(
                record.timestamp.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            dt = datetime.now(timezone.utc)

        # Write to date-partitioned file
        date_dir = self._dir / dt.strftime("%Y") / dt.strftime("%m")
        date_dir.mkdir(parents=True, exist_ok=True)
        file_path = date_dir / f"{dt.strftime('%d')}.jsonl"

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), default=str) + "\n")

        self._stats["total_added"] += 1
        return True

    def add_batch(self, records: list[DatasetRecord]) -> int:
        """Add a batch of records. Returns count of newly added."""
        added = sum(1 for r in records if self.add_event(r))
        logger.info(
            "Dataset: added %d/%d records (total=%d)",
            added, len(records), self._stats["total_added"],
        )
        return added

    def add_news_event(
        self,
        event: NewsEvent,
        event_type: str = "UNKNOWN",
        confidence: float = 0.5,
        affected_assets: Optional[list[str]] = None,
    ) -> bool:
        """Convenience: convert NewsEvent and add to dataset."""
        record = DatasetRecord.from_news_event(
            event, event_type, confidence, affected_assets,
        )
        return self.add_event(record)

    def query(
        self,
        domain: Optional[str] = None,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """
        Query the dataset with optional filters.
        Returns list of event dicts, most recent first.
        """
        results: list[dict] = []

        # Walk all jsonl files
        for jsonl_file in sorted(
            self._dir.rglob("*.jsonl"), reverse=True
        ):
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Apply filters
                    if domain and record.get("domain") != domain:
                        continue
                    if event_type and record.get("event_type") != event_type:
                        continue
                    if source and record.get("source") != source:
                        continue
                    if start_date and record.get("timestamp", "") < start_date:
                        continue
                    if end_date and record.get("timestamp", "") > end_date:
                        continue

                    results.append(record)
                    if len(results) >= limit:
                        return results

        return results

    def get_event_types(self) -> dict[str, int]:
        """Return counts by event_type."""
        counts: dict[str, int] = {}
        for jsonl_file in self._dir.rglob("*.jsonl"):
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        et = record.get("event_type", "UNKNOWN")
                        counts[et] = counts.get(et, 0) + 1
                    except (json.JSONDecodeError, AttributeError):
                        pass
        return counts

    def total_events(self) -> int:
        """Count total events in dataset."""
        count = 0
        for jsonl_file in self._dir.rglob("*.jsonl"):
            with open(jsonl_file, encoding="utf-8") as f:
                count += sum(1 for line in f if line.strip())
        return count
