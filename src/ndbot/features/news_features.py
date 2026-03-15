"""
Feature Engineering for News Events (Step 5).

Extracts structured features from raw news events for use in
alpha signal discovery models. Feature categories:

  1. Sentiment features     — polarity, magnitude, deviation from baseline
  2. Novelty features       — inverse document frequency, time since similar
  3. Entity features        — chokepoint presence, org importance, count
  4. Source features        — credibility weight, historical accuracy
  5. Temporal features      — hour of day, day of week, time since last event
  6. Text features          — headline length, keyword density, urgency words
  7. Clustering features    — corroboration count, cluster density
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from ..feeds.base import NewsEvent

logger = logging.getLogger(__name__)

# Urgency lexicon for detecting time-sensitive language
_URGENCY_WORDS = frozenset([
    "breaking", "urgent", "flash", "alert", "just in",
    "developing", "imminent", "emergency", "critical",
    "exclusive", "confirmed", "overnight",
])

# High-importance entity patterns
_CHOKEPOINT_ENTITIES = frozenset([
    "hormuz", "suez", "bab el-mandeb", "malacca",
    "bosphorus", "panama canal",
])

_KEY_ORGS = frozenset([
    "opec", "fed", "ecb", "boj", "imf", "nato",
    "openai", "google", "nvidia", "microsoft",
    "anthropic", "meta",
])


class NewsFeatureEngine:
    """
    Extracts a fixed-width feature vector from a NewsEvent.

    Maintains a rolling memory of recent events for computing
    relative/temporal features (novelty, corroboration, clustering).
    """

    def __init__(self, memory_window_minutes: int = 120):
        self._memory_window = timedelta(minutes=memory_window_minutes)
        self._recent_events: list[NewsEvent] = []
        self._keyword_counts: Counter = Counter()

    def extract(self, event: NewsEvent) -> dict[str, float]:
        """
        Extract feature dict from a single NewsEvent.

        Returns
        -------
        dict[str, float]
            Feature name → value mapping. All values are numeric.
        """
        self._prune_memory()
        features: dict[str, float] = {}

        # --- 1. Sentiment features ---
        features["sentiment_score"] = event.sentiment_score
        features["sentiment_magnitude"] = abs(event.sentiment_score)
        features["sentiment_positive"] = (
            1.0 if event.sentiment_score > 0.1 else 0.0
        )
        features["sentiment_negative"] = (
            1.0 if event.sentiment_score < -0.1 else 0.0
        )

        # Deviation from recent sentiment baseline
        if self._recent_events:
            baseline = sum(
                e.sentiment_score for e in self._recent_events
            ) / len(self._recent_events)
            features["sentiment_deviation"] = (
                event.sentiment_score - baseline
            )
        else:
            features["sentiment_deviation"] = 0.0

        # --- 2. Novelty features ---
        features["novelty_score"] = self._compute_novelty(event)
        features["time_since_similar_minutes"] = (
            self._time_since_similar(event)
        )

        # --- 3. Entity features ---
        features["entity_count"] = float(
            sum(len(v) for v in event.entities.values())
        )
        headline_lower = event.headline.lower()
        features["has_chokepoint"] = float(any(
            cp in headline_lower for cp in _CHOKEPOINT_ENTITIES
        ))
        features["has_key_org"] = float(any(
            org in headline_lower for org in _KEY_ORGS
        ))

        # --- 4. Source features ---
        features["source_credibility"] = event.credibility_weight
        features["importance_score"] = event.importance_score

        # --- 5. Temporal features ---
        hour = event.published_at.hour
        dow = event.published_at.weekday()
        features["hour_sin"] = math.sin(2 * math.pi * hour / 24)
        features["hour_cos"] = math.cos(2 * math.pi * hour / 24)
        features["dow_sin"] = math.sin(2 * math.pi * dow / 7)
        features["dow_cos"] = math.cos(2 * math.pi * dow / 7)
        features["is_weekend"] = float(dow >= 5)
        features["is_us_market_hours"] = float(14 <= hour <= 21)

        # Time since last event from any source
        if self._recent_events:
            last_ts = max(e.ingested_at for e in self._recent_events)
            delta_min = (
                event.ingested_at - last_ts
            ).total_seconds() / 60.0
            features["minutes_since_last_event"] = min(delta_min, 1440.0)
        else:
            features["minutes_since_last_event"] = 1440.0

        # --- 6. Text features ---
        features["headline_length"] = float(len(event.headline))
        features["headline_word_count"] = float(
            len(event.headline.split())
        )
        features["keyword_count"] = float(len(event.keywords_matched))
        features["keyword_density"] = (
            features["keyword_count"] / max(1, features["headline_word_count"])
        )
        features["has_urgency_word"] = float(any(
            w in headline_lower for w in _URGENCY_WORDS
        ))
        features["has_number"] = float(
            bool(re.search(r"\d+", event.headline))
        )
        features["has_percentage"] = float("%" in event.headline)

        # --- 7. Clustering features ---
        features["cluster_density"] = self._cluster_density(event)
        features["corroboration_count"] = self._corroboration_count(event)
        features["unique_sources_recent"] = float(len(set(
            e.source for e in self._recent_events
        )))

        # Update memory AFTER feature extraction
        self._recent_events.append(event)
        for kw in event.keywords_matched:
            self._keyword_counts[kw] += 1

        return features

    def feature_names(self) -> list[str]:
        """Return ordered list of all feature names."""
        return [
            "sentiment_score", "sentiment_magnitude",
            "sentiment_positive", "sentiment_negative",
            "sentiment_deviation",
            "novelty_score", "time_since_similar_minutes",
            "entity_count", "has_chokepoint", "has_key_org",
            "source_credibility", "importance_score",
            "hour_sin", "hour_cos", "dow_sin", "dow_cos",
            "is_weekend", "is_us_market_hours",
            "minutes_since_last_event",
            "headline_length", "headline_word_count",
            "keyword_count", "keyword_density",
            "has_urgency_word", "has_number", "has_percentage",
            "cluster_density", "corroboration_count",
            "unique_sources_recent",
        ]

    def _prune_memory(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._memory_window
        self._recent_events = [
            e for e in self._recent_events if e.ingested_at >= cutoff
        ]

    def _compute_novelty(self, event: NewsEvent) -> float:
        """
        Novelty score: inverse of keyword overlap with recent events.
        High novelty = new topic not seen recently. [0, 1].
        """
        if not event.keywords_matched or not self._recent_events:
            return 1.0
        kw_set = set(event.keywords_matched)
        total_overlap = 0
        for recent in self._recent_events:
            overlap = len(kw_set & set(recent.keywords_matched))
            total_overlap += overlap
        # Normalise: more overlap = less novelty
        max_possible = len(kw_set) * len(self._recent_events)
        if max_possible == 0:
            return 1.0
        overlap_ratio = total_overlap / max_possible
        return round(1.0 - overlap_ratio, 4)

    def _time_since_similar(self, event: NewsEvent) -> float:
        """Minutes since last event sharing >= 2 keywords."""
        if not event.keywords_matched:
            return 1440.0  # 24 hours (cap)
        kw_set = set(event.keywords_matched)
        for recent in reversed(self._recent_events):
            if len(kw_set & set(recent.keywords_matched)) >= 2:
                delta = (
                    event.ingested_at - recent.ingested_at
                ).total_seconds() / 60.0
                return min(delta, 1440.0)
        return 1440.0

    def _cluster_density(self, event: NewsEvent) -> float:
        """Count of recent events sharing at least one keyword."""
        if not event.keywords_matched:
            return 0.0
        kw_set = set(event.keywords_matched)
        return float(sum(
            1 for e in self._recent_events
            if kw_set & set(e.keywords_matched)
        ))

    def _corroboration_count(self, event: NewsEvent) -> float:
        """Distinct sources with similar headlines recently."""
        if not event.keywords_matched:
            return 0.0
        kw_set = set(event.keywords_matched)
        sources: set[str] = set()
        for e in self._recent_events:
            if (e.source != event.source
                    and len(kw_set & set(e.keywords_matched)) >= 2):
                sources.add(e.source)
        return float(len(sources))
