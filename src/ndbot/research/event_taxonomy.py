"""
Event taxonomy system — structured classification of market events.

Provides a hierarchical taxonomy of event types that the classifier
maps incoming news into. Each event type has:
  - A unique code
  - Parent domain
  - Expected market impact direction
  - Typical affected asset classes
  - Historical significance weight

The taxonomy is extensible — new event types can be registered
at runtime for research discovery.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ImpactDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    VOLATILE = "VOLATILE"  # Increases vol but unclear direction


@dataclass
class EventType:
    """A single event type in the taxonomy."""
    code: str
    domain: str
    label: str
    description: str
    expected_impact: ImpactDirection
    affected_sectors: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    significance_weight: float = 0.5  # [0, 1]
    historical_freq: float = 0.0  # Avg events per month

    def matches(self, text: str) -> float:
        """Score how well text matches this event type. [0, 1]."""
        text_lower = text.lower()
        if not self.keywords:
            return 0.0
        matched = sum(1 for kw in self.keywords if kw in text_lower)
        return min(1.0, matched / max(1, len(self.keywords) * 0.3))


# ---------------------------------------------------------------------------
# Default taxonomy
# ---------------------------------------------------------------------------

_DEFAULT_TAXONOMY: list[EventType] = [
    # Energy / Geopolitical
    EventType(
        "ENERGY_GEO_ATTACK", "ENERGY_GEO",
        "Energy Infrastructure Attack",
        "Military or terrorist attack on energy infrastructure",
        ImpactDirection.BULLISH,
        ["energy", "macro"],
        ["attack", "strike", "missile", "drone", "explosion",
         "pipeline", "refinery", "sabotage"],
        0.90, 2.0,
    ),
    EventType(
        "ENERGY_GEO_SANCTIONS", "ENERGY_GEO",
        "Energy Sanctions",
        "New sanctions affecting oil/gas producing nations",
        ImpactDirection.BULLISH,
        ["energy", "macro"],
        ["sanctions", "embargo", "ban", "restrict",
         "iran", "russia", "venezuela"],
        0.85, 1.5,
    ),
    EventType(
        "ENERGY_GEO_CHOKEPOINT", "ENERGY_GEO",
        "Chokepoint Disruption",
        "Disruption to major maritime energy transit chokepoint",
        ImpactDirection.BULLISH,
        ["energy", "macro"],
        ["hormuz", "suez", "bab el-mandeb", "malacca",
         "bosphorus", "blockade", "chokepoint"],
        0.95, 0.8,
    ),
    EventType(
        "ENERGY_SUPPLY_SHOCK", "ENERGY_GEO",
        "Supply Shock",
        "Unexpected change in energy supply",
        ImpactDirection.VOLATILE,
        ["energy"],
        ["opec", "supply cut", "production", "output",
         "shortage", "surplus", "inventory"],
        0.80, 3.0,
    ),
    EventType(
        "ENERGY_GEO_CEASEFIRE", "ENERGY_GEO",
        "Ceasefire / Peace Deal",
        "De-escalation in energy-producing region",
        ImpactDirection.BEARISH,
        ["energy", "macro"],
        ["ceasefire", "peace", "agreement", "deal",
         "negotiation", "truce"],
        0.70, 0.5,
    ),
    # AI / Technology
    EventType(
        "AI_MODEL_RELEASE", "AI_RELEASES",
        "Major AI Model Release",
        "Launch of significant new AI model or capability",
        ImpactDirection.BULLISH,
        ["ai", "semiconductors"],
        ["gpt", "claude", "gemini", "llama", "model release",
         "launch", "foundation model", "benchmark"],
        0.85, 4.0,
    ),
    EventType(
        "AI_DEVTOOLS_RELEASE", "AI_RELEASES",
        "AI Developer Tools Release",
        "New AI-powered developer tools or coding agents",
        ImpactDirection.BULLISH,
        ["ai", "semiconductors"],
        ["devin", "copilot", "coding agent", "devtools",
         "api", "sdk", "developer"],
        0.75, 3.0,
    ),
    EventType(
        "AI_SECURITY_BREACH", "AI_RELEASES",
        "AI Security Incident",
        "Security vulnerability or breach in AI system",
        ImpactDirection.BEARISH,
        ["ai"],
        ["jailbreak", "vulnerability", "breach", "exploit",
         "safety", "alignment", "incident"],
        0.80, 1.0,
    ),
    EventType(
        "AI_REGULATION", "AI_RELEASES",
        "AI Regulation Event",
        "Government action on AI regulation",
        ImpactDirection.BEARISH,
        ["ai"],
        ["regulation", "ban", "executive order", "legislation",
         "compliance", "oversight", "eu ai act"],
        0.75, 2.0,
    ),
    EventType(
        "AI_FUNDING", "AI_RELEASES",
        "AI Company Funding",
        "Major funding round or valuation event for AI company",
        ImpactDirection.BULLISH,
        ["ai"],
        ["funding", "valuation", "series", "investment",
         "raise", "billion", "unicorn"],
        0.70, 3.0,
    ),
    # Macro
    EventType(
        "MACRO_INTEREST_RATE", "MACRO",
        "Interest Rate Decision",
        "Central bank interest rate change or guidance",
        ImpactDirection.VOLATILE,
        ["macro"],
        ["interest rate", "fed", "ecb", "boj", "rate cut",
         "rate hike", "hawkish", "dovish", "fomc"],
        0.95, 1.0,
    ),
    EventType(
        "MACRO_INFLATION", "MACRO",
        "Inflation Data Release",
        "CPI, PPI, or other inflation data publication",
        ImpactDirection.VOLATILE,
        ["macro"],
        ["cpi", "ppi", "inflation", "consumer price",
         "deflation", "core inflation"],
        0.85, 1.0,
    ),
    EventType(
        "MACRO_EMPLOYMENT", "MACRO",
        "Employment Data",
        "Non-farm payrolls, unemployment, jobs data",
        ImpactDirection.VOLATILE,
        ["macro"],
        ["nonfarm", "payroll", "unemployment", "jobs",
         "labor market", "employment"],
        0.80, 1.0,
    ),
]


class EventTaxonomy:
    """
    Registry of event types with classification capabilities.

    The taxonomy is the bridge between raw news text and
    structured event categories that drive alpha discovery.
    """

    def __init__(self) -> None:
        self._types: dict[str, EventType] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load the built-in event taxonomy."""
        for et in _DEFAULT_TAXONOMY:
            self._types[et.code] = et
        logger.debug("Loaded %d event types", len(self._types))

    def register(self, event_type: EventType) -> None:
        """Register a new event type (for research extension)."""
        self._types[event_type.code] = event_type
        logger.info("Registered event type: %s", event_type.code)

    def get(self, code: str) -> Optional[EventType]:
        """Look up an event type by code."""
        return self._types.get(code)

    def all_types(self) -> list[EventType]:
        """Return all registered event types."""
        return list(self._types.values())

    def by_domain(self, domain: str) -> list[EventType]:
        """Filter event types by domain."""
        return [et for et in self._types.values() if et.domain == domain]

    def classify_text(self, text: str) -> list[tuple[str, float]]:
        """
        Score text against all event types.
        Returns list of (event_type_code, score) sorted by score desc.
        Only returns types with score > 0.
        """
        scores = []
        for code, et in self._types.items():
            score = et.matches(text)
            if score > 0:
                scores.append((code, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def classify_best(self, text: str) -> Optional[tuple[str, float]]:
        """Return the best-matching event type for text, or None."""
        matches = self.classify_text(text)
        return matches[0] if matches else None

    def to_list(self) -> list[dict]:
        """Serialise the full taxonomy."""
        return [
            {
                "code": et.code,
                "domain": et.domain,
                "label": et.label,
                "description": et.description,
                "expected_impact": et.expected_impact.value,
                "sectors": et.affected_sectors,
                "significance": et.significance_weight,
            }
            for et in self._types.values()
        ]
