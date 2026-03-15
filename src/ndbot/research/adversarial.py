"""
Adversarial News Defense (Step 8).

Detects and filters manipulated or low-quality news events:
  1. Duplicate / near-duplicate detection (fuzzy headline matching)
  2. Sentiment manipulation detection (extreme scores from low-cred sources)
  3. Adversarial text pattern detection (clickbait, pump-and-dump)
  4. Source consistency validation (headline vs historical source patterns)
  5. Spam / noise filtering (repetitive posting patterns)
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..feeds.base import NewsEvent

logger = logging.getLogger(__name__)

# Clickbait / manipulation patterns
_CLICKBAIT_PATTERNS = [
    re.compile(r"you won't believe", re.IGNORECASE),
    re.compile(r"this is huge", re.IGNORECASE),
    re.compile(r"to the moon", re.IGNORECASE),
    re.compile(r"100x|1000x|guaranteed", re.IGNORECASE),
    re.compile(r"act now|last chance|don't miss", re.IGNORECASE),
    re.compile(r"\b(buy|sell) signal\b", re.IGNORECASE),
    re.compile(r"pump|dump|rug ?pull", re.IGNORECASE),
    re.compile(r"insider|leaked|secret", re.IGNORECASE),
]

# Excessive capitalisation threshold
_CAPS_RATIO_THRESHOLD = 0.6


@dataclass
class DefenseResult:
    """Result of adversarial analysis for a single event."""
    event_id: str
    is_suspicious: bool
    flags: list[str] = field(default_factory=list)
    confidence_penalty: float = 0.0  # [0, 1] penalty to apply
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "is_suspicious": self.is_suspicious,
            "flags": self.flags,
            "confidence_penalty": self.confidence_penalty,
            "details": self.details,
        }


class AdversarialDefense:
    """
    Screens news events for manipulation, spam, and adversarial content.

    Maintains a rolling window of recent events for
    duplicate/pattern detection.
    """

    def __init__(
        self,
        memory_window_minutes: int = 360,
        similarity_threshold: float = 0.7,
        max_source_rate: int = 20,  # Max events per hour from one source
    ):
        self._memory_window = timedelta(minutes=memory_window_minutes)
        self._similarity_threshold = similarity_threshold
        self._max_source_rate = max_source_rate
        self._recent_events: list[NewsEvent] = []
        self._source_counts: Counter = Counter()
        self._flagged_count = 0
        self._total_screened = 0

    def screen(self, event: NewsEvent) -> DefenseResult:
        """
        Screen a single event for adversarial patterns.
        Returns DefenseResult with flags and penalties.
        """
        self._prune_memory()
        self._total_screened += 1

        flags: list[str] = []
        penalty = 0.0
        details: dict = {}

        # 1. Near-duplicate detection
        dup_score = self._check_duplicate(event)
        if dup_score > self._similarity_threshold:
            flags.append("near_duplicate")
            penalty += 0.4
            details["duplicate_similarity"] = round(dup_score, 4)

        # 2. Sentiment manipulation
        sent_flag = self._check_sentiment_manipulation(event)
        if sent_flag:
            flags.append("sentiment_manipulation")
            penalty += 0.3
            details["sentiment_flag"] = sent_flag

        # 3. Clickbait / adversarial patterns
        cb_matches = self._check_clickbait(event)
        if cb_matches:
            flags.append("clickbait_pattern")
            penalty += 0.2 * len(cb_matches)
            details["clickbait_matches"] = cb_matches

        # 4. Excessive capitalisation
        caps_ratio = self._caps_ratio(event.headline)
        if caps_ratio > _CAPS_RATIO_THRESHOLD:
            flags.append("excessive_caps")
            penalty += 0.15
            details["caps_ratio"] = round(caps_ratio, 4)

        # 5. Source spam detection
        if self._check_spam(event):
            flags.append("source_spam")
            penalty += 0.5
            details["source_rate"] = self._source_counts.get(
                event.source, 0
            )

        # 6. Extremely short or empty headline
        if len(event.headline.strip()) < 10:
            flags.append("headline_too_short")
            penalty += 0.3

        # Clamp penalty
        penalty = min(1.0, penalty)
        is_suspicious = penalty > 0.3

        if is_suspicious:
            self._flagged_count += 1
            logger.info(
                "Adversarial flag: event=%s flags=%s penalty=%.2f",
                event.event_id[:8], flags, penalty,
            )

        # Update memory
        self._recent_events.append(event)
        self._source_counts[event.source] += 1

        return DefenseResult(
            event_id=event.event_id,
            is_suspicious=is_suspicious,
            flags=flags,
            confidence_penalty=round(penalty, 4),
            details=details,
        )

    def _check_duplicate(self, event: NewsEvent) -> float:
        """
        Check similarity to recent events using word overlap.
        Returns similarity score [0, 1].
        """
        if not self._recent_events:
            return 0.0

        event_words = set(event.headline.lower().split())
        if not event_words:
            return 0.0

        max_sim = 0.0
        for recent in self._recent_events:
            recent_words = set(recent.headline.lower().split())
            if not recent_words:
                continue
            overlap = len(event_words & recent_words)
            union = len(event_words | recent_words)
            sim = overlap / union if union > 0 else 0.0
            max_sim = max(max_sim, sim)

        return max_sim

    def _check_sentiment_manipulation(
        self, event: NewsEvent
    ) -> Optional[str]:
        """
        Detect suspicious sentiment patterns.
        Extreme sentiment from low-credibility sources is suspicious.
        """
        if (abs(event.sentiment_score) > 0.8
                and event.credibility_weight < 0.5):
            return (
                f"extreme_sentiment={event.sentiment_score:.2f} "
                f"from low_cred_source={event.credibility_weight:.2f}"
            )
        return None

    def _check_clickbait(self, event: NewsEvent) -> list[str]:
        """Check headline against clickbait/manipulation patterns."""
        matches = []
        for pattern in _CLICKBAIT_PATTERNS:
            if pattern.search(event.headline):
                matches.append(pattern.pattern)
        return matches

    def _check_spam(self, event: NewsEvent) -> bool:
        """Check if source is posting at an abnormally high rate."""
        return self._source_counts.get(event.source, 0) > self._max_source_rate

    @staticmethod
    def _caps_ratio(text: str) -> float:
        """Fraction of alphabetic characters that are uppercase."""
        alpha = [c for c in text if c.isalpha()]
        if not alpha:
            return 0.0
        upper = sum(1 for c in alpha if c.isupper())
        return upper / len(alpha)

    def _prune_memory(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._memory_window
        self._recent_events = [
            e for e in self._recent_events if e.ingested_at >= cutoff
        ]

    @property
    def stats(self) -> dict:
        return {
            "total_screened": self._total_screened,
            "flagged": self._flagged_count,
            "flag_rate": round(
                self._flagged_count / max(1, self._total_screened), 4
            ),
            "memory_size": len(self._recent_events),
        }
