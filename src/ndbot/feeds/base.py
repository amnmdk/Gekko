"""
Base types and abstract interface for news feeds.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventDomain(str, Enum):
    ENERGY_GEO = "ENERGY_GEO"
    AI_RELEASES = "AI_RELEASES"
    UNKNOWN = "UNKNOWN"


@dataclass
class NewsEvent:
    """
    A single normalised news event ingested from any feed.
    All fields are intentionally simple — no heavy objects.
    """
    event_id: str                          # Deterministic hash of (source, url, headline)
    domain: EventDomain
    headline: str
    summary: str
    source: str                            # Feed name / publisher
    url: str
    published_at: datetime                 # UTC
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    credibility_weight: float = 1.0        # From feed config
    raw_tags: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    # Populated by classifier
    keywords_matched: list[str] = field(default_factory=list)
    sentiment_score: float = 0.0           # [-1, 1]
    importance_score: float = 0.5          # [0, 1]

    @classmethod
    def make_id(cls, source: str, url: str, headline: str) -> str:
        raw = f"{source}|{url}|{headline}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "domain": self.domain.value,
            "headline": self.headline,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "credibility_weight": self.credibility_weight,
            "raw_tags": self.raw_tags,
            "entities": self.entities,
            "keywords_matched": self.keywords_matched,
            "sentiment_score": self.sentiment_score,
            "importance_score": self.importance_score,
        }


class BaseFeed(ABC):
    """Abstract base for all feed implementations."""

    def __init__(self, name: str, domain: EventDomain, credibility_weight: float = 1.0):
        self.name = name
        self.domain = domain
        self.credibility_weight = credibility_weight
        self._seen_ids: set[str] = set()

    def _is_new(self, event_id: str) -> bool:
        if event_id in self._seen_ids:
            return False
        self._seen_ids.add(event_id)
        return True

    @abstractmethod
    async def poll(self) -> list[NewsEvent]:
        """Fetch new events since last poll. Returns only unseen events."""
        ...
