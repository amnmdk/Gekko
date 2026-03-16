"""
Default RSS feed definitions for live mode.

Each entry is (name, url, credibility_weight).
These are free, public RSS feeds — no API key needed.
"""
from __future__ import annotations

# ── Energy / Geopolitics ─────────────────────────────────────────────────────
ENERGY_GEO_FEEDS: list[tuple[str, str, float]] = [
    (
        "bbc-world",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        1.7,
    ),
    (
        "aljazeera",
        "https://www.aljazeera.com/xml/rss/all.xml",
        1.5,
    ),
    (
        "reuters-world",
        "https://feeds.reuters.com/reuters/worldNews",
        1.8,
    ),
    (
        "bbc-business",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        1.4,
    ),
]

# ── AI / Tech Releases ───────────────────────────────────────────────────────
AI_RELEASES_FEEDS: list[tuple[str, str, float]] = [
    (
        "techcrunch",
        "https://techcrunch.com/feed/",
        1.5,
    ),
    (
        "theverge",
        "https://www.theverge.com/rss/index.xml",
        1.3,
    ),
    (
        "ars-technica",
        "https://feeds.arstechnica.com/arstechnica/index",
        1.4,
    ),
    (
        "hackernews-best",
        "https://hnrss.org/best",
        1.2,
    ),
]
