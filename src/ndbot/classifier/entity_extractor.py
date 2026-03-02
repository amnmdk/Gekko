"""
Lightweight named entity recognition via rule-based pattern matching.
No spaCy, no NLTK — pure regex / keyword matching.

Extracts:
  - LOCATION  : known geopolitical locations and chokepoints
  - ORG       : known organisations (AI labs, energy companies, agencies)
  - COMMODITY : energy commodities
  - TECHNOLOGY: AI technologies and systems
"""
from __future__ import annotations

import re
from typing import Optional

from ..feeds.base import NewsEvent


# ---------------------------------------------------------------------------
# Entity dictionaries
# ---------------------------------------------------------------------------

_LOCATIONS: list[str] = [
    "Iran", "Iraq", "Saudi Arabia", "Yemen", "Libya", "Nigeria", "Algeria",
    "UAE", "Qatar", "Kuwait", "Bahrain", "Oman",
    "Hormuz", "Suez", "Bab el-Mandeb", "Bosphorus", "Persian Gulf",
    "Red Sea", "Gulf of Aden", "Gulf of Guinea", "Arabian Sea",
    "Nigeria", "Angola", "Mozambique", "Tanzania",
    "Russia", "Ukraine", "Turkey", "Egypt", "Morocco",
    "Black Sea", "Mediterranean",
]

_ORGS: list[str] = [
    # Energy
    "OPEC", "OPEC+", "IEA", "EIA", "Aramco", "ADNOC", "Sonatrach",
    "Shell", "BP", "Total", "ExxonMobil", "Chevron",
    "Gazprom", "Rosneft", "NIOC", "NOC",
    # AI labs
    "OpenAI", "Anthropic", "Google DeepMind", "DeepMind", "Meta AI",
    "Microsoft", "Mistral", "Cohere", "Cerebras", "Inflection",
    "Stability AI", "Hugging Face",
    # Regulators
    "EU", "FTC", "EDPB", "SEC", "CFTC",
    # Militaries / factions
    "Houthi", "IRGC", "NATO", "US Navy", "Pentagon",
]

_COMMODITIES: list[str] = [
    "crude oil", "Brent", "WTI", "natural gas", "LNG", "LPG",
    "diesel", "gasoline", "naphtha", "jet fuel", "refinery",
]

_TECHNOLOGIES: list[str] = [
    "GPT-5", "GPT-4", "GPT-3", "Claude", "Gemini", "LLaMA", "Mistral",
    "DALL-E", "Sora", "Whisper", "Devin",
    "transformer", "LLM", "foundation model", "diffusion model",
    "reinforcement learning", "RLHF", "constitutional AI",
]


def _build_pattern(terms: list[str]) -> re.Pattern:
    """Build a case-insensitive alternation pattern for all terms."""
    escaped = sorted([re.escape(t) for t in terms], key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


_LOC_RE = _build_pattern(_LOCATIONS)
_ORG_RE = _build_pattern(_ORGS)
_COM_RE = _build_pattern(_COMMODITIES)
_TEC_RE = _build_pattern(_TECHNOLOGIES)


class EntityExtractor:
    """Extract named entities from news event text."""

    def extract(self, text: str) -> dict[str, list[str]]:
        """
        Returns a dict with keys: LOCATION, ORG, COMMODITY, TECHNOLOGY.
        Values are deduplicated lists of matched strings (original casing).
        """
        def _find(pattern: re.Pattern) -> list[str]:
            return list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))

        return {
            "LOCATION": _find(_LOC_RE),
            "ORG": _find(_ORG_RE),
            "COMMODITY": _find(_COM_RE),
            "TECHNOLOGY": _find(_TEC_RE),
        }

    def enrich(self, event: NewsEvent) -> NewsEvent:
        """Extract entities from event headline+summary and attach to event."""
        text = event.headline + " " + event.summary
        event.entities = self.extract(text)
        return event

    def entity_importance_score(self, entities: dict[str, list[str]]) -> float:
        """
        Heuristic importance score based on entity count and type.
        Returns a score in [0, 1].
        """
        score = 0.0
        # High-value locations (chokepoints)
        chokepoints = {"hormuz", "suez", "bab el-mandeb", "bosphorus"}
        for loc in entities.get("LOCATION", []):
            if loc.lower() in chokepoints:
                score += 0.3
            else:
                score += 0.05
        # Orgs
        score += len(entities.get("ORG", [])) * 0.05
        # Commodities
        score += len(entities.get("COMMODITY", [])) * 0.04
        # Technologies
        score += len(entities.get("TECHNOLOGY", [])) * 0.06
        return min(1.0, score)
