"""
Dynamic confidence scoring model.

Uses a Bayesian-style posterior update over four evidence dimensions:
  1. Source credibility weight (from feed config)
  2. Headline clustering density  (how many recent events share keywords)
  3. Corroboration count         (how many sources published similar headlines)
  4. Entity importance weight    (extracted chokepoints / key organisations)

Prior: 0.5 (maximum uncertainty)
Each evidence dimension shifts the log-odds proportionally.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from ..feeds.base import NewsEvent


def _logit(p: float) -> float:
    """Convert probability *p* to log-odds, clamped to avoid ±infinity."""
    p = max(1e-9, min(1 - 1e-9, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    """Convert log-odds *x* back to probability [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))


class ConfidenceModel:
    """
    Computes a composite confidence score [0, 1] for a news event.

    Maintains a short-term memory of recent events to enable
    clustering density and corroboration calculations.
    """

    def __init__(
        self,
        memory_window_minutes: int = 60,
        cluster_boost_max: float = 0.3,
        corroboration_boost_max: float = 0.25,
    ):
        self._memory_window = timedelta(minutes=memory_window_minutes)
        self._cluster_boost_max = cluster_boost_max
        self._corroboration_boost_max = corroboration_boost_max
        self._recent_events: list[NewsEvent] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, event: NewsEvent) -> float:
        """
        Compute confidence score for *event* given current memory state.
        Returns float in [0, 1].
        """
        self._prune_memory()
        score = self._compute(event)
        # Update memory AFTER scoring (event not counted towards itself)
        self._recent_events.append(event)
        return score

    def _compute(self, event: NewsEvent) -> float:
        """Bayesian log-odds update across five evidence dimensions."""
        # Start at log-odds of prior 0.5 (= 0)
        log_odds = 0.0

        # --- 1. Source credibility ---
        # Maps [0, 2] to log-odds shift [-1.5, +1.5]
        cred = event.credibility_weight
        log_odds += _logit(min(0.99, max(0.01, cred / 2.0)))

        # --- 2. Importance score (from classifier / entity extractor) ---
        # Maps [0, 1] to log-odds shift [-1.5, +1.5]
        imp = event.importance_score
        log_odds += _logit(min(0.99, max(0.01, imp)))

        # --- 3. Clustering density ---
        density = self._cluster_density(event)
        # density ∈ [0, N_recent] → boost ∈ [0, cluster_boost_max]
        density_boost = self._cluster_boost_max * math.tanh(density / 3.0)
        log_odds += _logit(0.5 + density_boost)

        # --- 4. Corroboration ---
        corr = self._corroboration_count(event)
        corr_boost = self._corroboration_boost_max * math.tanh(corr / 2.0)
        log_odds += _logit(0.5 + corr_boost)

        # --- 5. Sentiment magnitude (high magnitude events are more significant) ---
        sent_mag = abs(event.sentiment_score)
        log_odds += _logit(min(0.99, max(0.01, 0.5 + sent_mag * 0.3)))

        # Normalise back to probability
        raw = _sigmoid(log_odds)
        # Clip to [0.05, 0.95] — never absolutely certain or absolutely null
        return round(min(0.95, max(0.05, raw)), 4)

    def _prune_memory(self) -> None:
        """Remove events older than the memory window."""
        cutoff = datetime.now(timezone.utc) - self._memory_window
        self._recent_events = [
            ev for ev in self._recent_events if ev.ingested_at >= cutoff
        ]

    def _cluster_density(self, event: NewsEvent) -> float:
        """
        Count how many recent events share at least one keyword with *event*.
        Returns a raw count (not normalised).
        """
        if not event.keywords_matched:
            return 0.0
        kw_set = set(event.keywords_matched)
        count = sum(
            1 for ev in self._recent_events
            if kw_set & set(ev.keywords_matched)
        )
        return float(count)

    def _corroboration_count(self, event: NewsEvent) -> float:
        """
        Count distinct sources that published a similar headline recently.
        Simple heuristic: share ≥2 keywords AND different source name.
        """
        if not event.keywords_matched:
            return 0.0
        kw_set = set(event.keywords_matched)
        sources_seen: set[str] = set()
        for ev in self._recent_events:
            if ev.source != event.source and len(kw_set & set(ev.keywords_matched)) >= 2:
                sources_seen.add(ev.source)
        return float(len(sources_seen))
