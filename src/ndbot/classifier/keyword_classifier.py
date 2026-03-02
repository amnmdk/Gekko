"""
Lightweight keyword-based event classifier.
No transformers, no heavy models — designed for Raspberry Pi 5.

Architecture
------------
- Two independent keyword dictionaries (ENERGY_GEO, AI_RELEASES)
- Each keyword entry has a weight [0, 1]
- Score = sum of matched weights / normalisation constant
- Sentiment: polarity keyword lookup
- Importance: keyword importance weight average

All matching is case-insensitive substring search.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..feeds.base import EventDomain, NewsEvent


# ---------------------------------------------------------------------------
# Keyword dictionaries
# (keyword, domain_score_weight, sentiment_contribution, importance_contribution)
# ---------------------------------------------------------------------------

_ENERGY_GEO_KEYWORDS: list[tuple[str, float, float, float]] = [
    # Chokepoints
    ("strait of hormuz",    0.95, -0.8, 0.95),
    ("hormuz",              0.80, -0.6, 0.85),
    ("suez canal",          0.90, -0.5, 0.90),
    ("bab el-mandeb",       0.95, -0.7, 0.92),
    ("bosphorus",           0.75, -0.4, 0.75),
    ("strait of malacca",   0.70, -0.4, 0.70),
    # Geopolitics
    ("iran sanctions",      0.90, -0.7, 0.90),
    ("houthi",              0.88, -0.8, 0.88),
    ("yemeni",              0.70, -0.6, 0.72),
    ("red sea attack",      0.92, -0.85, 0.92),
    ("red sea",             0.65, -0.5, 0.70),
    ("opec",                0.80,  0.0, 0.75),
    ("opec+",               0.82,  0.0, 0.78),
    ("aramco",              0.85, -0.3, 0.80),
    ("refinery attack",     0.90, -0.85, 0.90),
    ("pipeline attack",     0.90, -0.85, 0.90),
    ("pipeline sabotage",   0.92, -0.88, 0.92),
    ("oil supply",          0.70, -0.3, 0.65),
    ("crude supply",        0.72, -0.3, 0.65),
    ("tanker",              0.65, -0.2, 0.60),
    ("lng",                 0.62,  0.0, 0.58),
    ("nigeria",             0.60, -0.2, 0.62),
    ("libya",               0.65, -0.3, 0.65),
    ("algeria",             0.60, -0.2, 0.58),
    ("iraq",                0.68, -0.3, 0.68),
    ("gulf of guinea",      0.65, -0.4, 0.65),
    ("persian gulf",        0.72, -0.4, 0.72),
    ("missile strike",      0.80, -0.85, 0.85),
    ("drone strike",        0.78, -0.82, 0.83),
    ("naval",               0.60, -0.3, 0.58),
    ("geopolitical",        0.55,  0.0, 0.55),
    ("blockade",            0.82, -0.75, 0.82),
    ("embargo",             0.80, -0.70, 0.80),
    ("ceasefire",           0.70,  0.50, 0.65),
    ("peace deal",          0.65,  0.55, 0.60),
    # Commodities
    ("crude oil",           0.65,  0.0, 0.60),
    ("brent",               0.65,  0.0, 0.60),
    ("wti",                 0.65,  0.0, 0.60),
    ("natural gas",         0.62,  0.0, 0.58),
]

_AI_RELEASES_KEYWORDS: list[tuple[str, float, float, float]] = [
    # OpenAI
    ("openai",              0.85,  0.3, 0.85),
    ("gpt-5",               0.95,  0.8, 0.95),
    ("gpt-4",               0.88,  0.7, 0.88),
    ("chatgpt",             0.80,  0.4, 0.80),
    ("o1 model",            0.85,  0.7, 0.85),
    ("operator",            0.78,  0.6, 0.78),
    # Anthropic
    ("anthropic",           0.85,  0.3, 0.85),
    ("claude",              0.82,  0.4, 0.82),
    ("constitutional ai",   0.78,  0.5, 0.78),
    # DeepMind / Google
    ("deepmind",            0.82,  0.3, 0.82),
    ("gemini",              0.80,  0.5, 0.80),
    ("google ai",           0.75,  0.3, 0.75),
    # Meta
    ("llama",               0.80,  0.5, 0.80),
    ("meta ai",             0.75,  0.3, 0.75),
    ("open source llm",     0.72,  0.4, 0.72),
    # General AI milestones
    ("large language model", 0.70, 0.2, 0.70),
    ("foundation model",    0.68,  0.2, 0.68),
    ("ai agent",            0.75,  0.5, 0.75),
    ("coding agent",        0.78,  0.6, 0.78),
    ("autonomous agent",    0.78,  0.6, 0.78),
    ("ai releases",         0.80,  0.4, 0.80),
    ("model release",       0.82,  0.5, 0.82),
    ("benchmark",           0.65,  0.3, 0.65),
    ("safety",              0.60, -0.1, 0.60),
    ("jailbreak",           0.75, -0.7, 0.80),
    ("vulnerability",       0.72, -0.6, 0.75),
    ("outage",              0.70, -0.5, 0.72),
    ("valuation",           0.65,  0.4, 0.65),
    ("funding round",       0.68,  0.5, 0.68),
    ("regulatory",          0.65, -0.3, 0.65),
    ("ban",                 0.72, -0.5, 0.72),
    ("inference",           0.60,  0.3, 0.60),
    ("training data",       0.60,  0.0, 0.60),
    ("parameter",           0.55,  0.2, 0.55),
    ("token",               0.50,  0.1, 0.50),
    ("devin",               0.78,  0.6, 0.78),
    ("mistral",             0.75,  0.4, 0.75),
    ("cerebras",            0.70,  0.4, 0.70),
]


@dataclass
class ClassificationResult:
    domain: EventDomain
    confidence: float           # [0, 1] match confidence
    keywords_matched: list[str]
    sentiment_score: float      # [-1, 1]
    importance_score: float     # [0, 1]


class KeywordClassifier:
    """
    Rule-based classifier using weighted keyword matching.
    Scales to high throughput on constrained hardware.
    """

    def __init__(self):
        self._energy_kws = _ENERGY_GEO_KEYWORDS
        self._ai_kws = _AI_RELEASES_KEYWORDS

    def classify(self, event: NewsEvent) -> ClassificationResult:
        text = (event.headline + " " + event.summary).lower()

        energy_score, energy_matches, e_sent, e_imp = self._score(text, self._energy_kws)
        ai_score, ai_matches, a_sent, a_imp = self._score(text, self._ai_kws)

        if energy_score == 0 and ai_score == 0:
            return ClassificationResult(
                domain=EventDomain.UNKNOWN,
                confidence=0.0,
                keywords_matched=[],
                sentiment_score=0.0,
                importance_score=0.3,
            )

        if energy_score >= ai_score:
            norm = min(1.0, energy_score / 3.0)
            return ClassificationResult(
                domain=EventDomain.ENERGY_GEO,
                confidence=norm,
                keywords_matched=energy_matches,
                sentiment_score=e_sent,
                importance_score=e_imp,
            )
        else:
            norm = min(1.0, ai_score / 3.0)
            return ClassificationResult(
                domain=EventDomain.AI_RELEASES,
                confidence=norm,
                keywords_matched=ai_matches,
                sentiment_score=a_sent,
                importance_score=a_imp,
            )

    def _score(
        self, text: str, keywords: list[tuple[str, float, float, float]]
    ) -> tuple[float, list[str], float, float]:
        total_weight = 0.0
        total_sentiment = 0.0
        total_importance = 0.0
        matched: list[str] = []
        for kw, weight, sent, imp in keywords:
            if kw in text:
                total_weight += weight
                total_sentiment += sent * weight
                total_importance += imp * weight
                matched.append(kw)

        if not matched:
            return 0.0, [], 0.0, 0.5

        avg_sentiment = total_sentiment / total_weight
        avg_importance = min(1.0, total_importance / total_weight)
        return total_weight, matched, avg_sentiment, avg_importance

    def enrich(self, event: NewsEvent) -> NewsEvent:
        """Classify *event* in-place and return it."""
        result = self.classify(event)
        # Only override domain if classifier is more specific
        if result.domain != EventDomain.UNKNOWN:
            event.domain = result.domain
        event.keywords_matched = result.keywords_matched
        event.sentiment_score = result.sentiment_score
        event.importance_score = result.importance_score
        return event
