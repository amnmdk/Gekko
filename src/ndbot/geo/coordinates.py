"""
Map news event content to approximate geographic coordinates.
Used to place markers on the Leaflet.js map.
"""
from __future__ import annotations
import random
from ..feeds.base import EventDomain, NewsEvent

# ---------------------------------------------------------------------------
# Keyword → (lat, lon, label) lookup tables
# ---------------------------------------------------------------------------

_ENERGY_GEO_LOCATIONS: list[tuple[list[str], float, float, str]] = [
    (["strait of hormuz", "hormuz"],        26.5,   56.5,  "Strait of Hormuz"),
    (["houthi", "bab el-mandeb", "yemen"],  12.5,   43.5,  "Bab el-Mandeb"),
    (["red sea"],                            20.0,   38.0,  "Red Sea"),
    (["suez", "egypt"],                     30.0,   32.5,  "Suez Canal"),
    (["iran"],                              32.0,   53.0,  "Iran"),
    (["saudi", "aramco", "ras tanura"],     24.0,   45.0,  "Saudi Arabia"),
    (["iraq", "kirkuk"],                    33.0,   44.0,  "Iraq"),
    (["russia", "moscow"],                  55.7,   37.6,  "Russia"),
    (["ukraine", "kyiv"],                   50.5,   30.5,  "Ukraine"),
    (["turkey", "bosphorus", "ankara"],     39.9,   32.9,  "Turkey"),
    (["libya"],                             26.3,   17.2,  "Libya"),
    (["nigeria", "niger delta"],             6.5,    3.4,  "Nigeria"),
    (["west africa"],                        5.0,   -1.0,  "West Africa"),
    (["algeria"],                           28.0,    1.7,  "Algeria"),
    (["morocco"],                           31.8,   -7.1,  "Morocco"),
    (["north sea"],                         56.0,    3.0,  "North Sea"),
    (["caspian"],                           42.0,   50.0,  "Caspian Sea"),
    (["gulf of guinea"],                     3.0,    2.0,  "Gulf of Guinea"),
    (["opec"],                              24.0,   45.0,  "OPEC / Riyadh"),
    (["persian gulf"],                      26.5,   52.0,  "Persian Gulf"),
    (["uae", "abu dhabi"],                  24.5,   54.4,  "UAE"),
    (["adnoc"],                             24.5,   54.4,  "UAE"),
    (["spain", "enagas"],                   40.4,   -3.7,  "Spain"),
    (["eu", "europe", "lloyd"],             50.8,    4.3,  "Europe"),
]

_AI_RELEASES_LOCATIONS: list[tuple[list[str], float, float, str]] = [
    (["openai", "chatgpt", "gpt"],          37.78, -122.39, "OpenAI – San Francisco"),
    (["anthropic", "claude"],               37.77, -122.41, "Anthropic – San Francisco"),
    (["google", "deepmind", "gemini"],      37.42, -122.08, "Google – Mountain View"),
    (["meta", "llama"],                     37.48, -122.15, "Meta – Menlo Park"),
    (["microsoft", "copilot", "azure"],     47.64, -122.13, "Microsoft – Redmond"),
    (["nvidia", "cerebras"],                37.37, -121.96, "Silicon Valley"),
    (["mistral"],                           48.85,    2.35, "Mistral – Paris"),
    (["china", "baidu", "alibaba"],         39.9,   116.4,  "China – Beijing"),
    (["eu", "europe", "gdpr"],              50.85,   4.35,  "EU – Brussels"),
    (["uk", "london"],                      51.5,   -0.1,   "UK – London"),
    (["japan"],                             35.7,   139.7,  "Japan – Tokyo"),
    (["devin", "cognition"],                37.76, -122.42, "SF Bay Area"),
    (["neurips", "research", "paper"],      37.78, -122.39, "Research Hub"),
]

# Fallback pools: a few dozen plausible coords per domain
_ENERGY_FALLBACKS: list[tuple[float, float]] = [
    (26.5, 56.5), (20.0, 38.0), (24.0, 45.0), (32.0, 53.0),
    (56.0, 3.0),  (6.5, 3.4),  (33.0, 44.0), (28.0, 1.7),
]
_AI_FALLBACKS: list[tuple[float, float]] = [
    (37.78, -122.39), (37.42, -122.08), (47.64, -122.13),
    (48.85, 2.35),    (51.5, -0.1),    (39.9, 116.4),
]

_rng = random.Random()


def get_event_coordinates(event: NewsEvent) -> tuple[float, float]:
    """Return (lat, lon) for a news event based on its content."""
    text = (event.headline + " " + event.summary).lower()
    table = (
        _ENERGY_GEO_LOCATIONS
        if event.domain == EventDomain.ENERGY_GEO
        else _AI_RELEASES_LOCATIONS
    )
    for keywords, lat, lon, _ in table:
        if any(kw in text for kw in keywords):
            # Small jitter so overlapping events don't stack exactly
            return (
                round(lat + _rng.uniform(-0.8, 0.8), 4),
                round(lon + _rng.uniform(-0.8, 0.8), 4),
            )
    # Fallback: pick from domain pool
    fallbacks = (
        _ENERGY_FALLBACKS
        if event.domain == EventDomain.ENERGY_GEO
        else _AI_FALLBACKS
    )
    base = _rng.choice(fallbacks)
    return (
        round(base[0] + _rng.uniform(-2.0, 2.0), 4),
        round(base[1] + _rng.uniform(-2.0, 2.0), 4),
    )
