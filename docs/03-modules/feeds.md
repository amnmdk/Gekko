# Feeds Module

> `src/ndbot/feeds/` — News ingestion from RSS feeds and synthetic generators

---

## Overview

The feeds module is responsible for getting news events into the system. It supports two sources:

1. **RSS/Atom feeds** — Real news from the internet (used in `paper` mode)
2. **Synthetic feeds** — Deterministic fake events for testing (used in `simulate` mode)

---

## NewsEvent

The core data type for all ingested news:

```python
@dataclass
class NewsEvent:
    event_id: str              # SHA-256 hash of (source, url, headline)
    domain: EventDomain        # ENERGY_GEO | AI_RELEASES | UNKNOWN
    headline: str              # Event title
    summary: str               # Full text or description
    source: str                # Feed name (e.g., "reuters-commodities")
    url: str                   # Original article URL
    published_at: datetime     # Publication timestamp (UTC)
    ingested_at: datetime      # When ndbot first saw it (auto-set)
    credibility_weight: float  # Source reliability [0.0, 2.0]
    raw_tags: list[str]        # RSS category tags
    entities: dict             # Extracted NER: {"ORG": [...], "LOCATION": [...]}
    keywords_matched: list     # Matched keywords from classifier
    sentiment_score: float     # [-1.0, +1.0] bearish to bullish
    importance_score: float    # [0.0, 1.0] event significance
```

### Event Deduplication

Events are deduplicated by `event_id`, which is a deterministic hash:

```python
event_id = sha256(f"{source}:{url}:{headline}".encode()).hexdigest()[:16]
```

The `BaseFeed` base class tracks seen IDs in memory via `_seen_ids: set[str]`. The database also enforces uniqueness — inserting the same event twice stores exactly one row.

---

## RSSFeed

Async RSS/Atom feed reader with exponential backoff retry.

### Configuration

```yaml
feeds:
  - name: "reuters-commodities"
    url: "https://feeds.reuters.com/reuters/commoditiesNews"
    domain: ENERGY_GEO
    poll_interval_seconds: 60
    credibility_weight: 1.8
    enabled: true
```

### Retry Policy

| Condition | Action |
|---|---|
| HTTP 200 | Return parsed entries |
| HTTP 429 (Rate Limited) | Retry with 2s/4s/8s backoff |
| Timeout (15s) | Retry with backoff |
| Network error | Retry with backoff |
| Other HTTP error | Fail immediately |
| 3 retries exhausted | Return empty list |

### Credibility Weight Guidelines

| Weight | Source Type | Example |
|---|---|---|
| `2.0` | Primary source | Reuters, official lab blog |
| `1.5` | Tier-1 financial media | FT, Bloomberg |
| `1.2` | Specialist industry | OilPrice, The Decoder |
| `1.0` | General aggregator | TechCrunch |
| `0.8` | Unverified source | Forum, social media |

---

## SyntheticFeed

Deterministic event generator for testing and development. Uses Python's `random.Random` with a fixed seed for reproducibility.

### Usage

```python
from ndbot.feeds.synthetic import SyntheticFeed
from ndbot.feeds.base import EventDomain

feed = SyntheticFeed(
    domain=EventDomain.ENERGY_GEO,
    seed=42,
    start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    time_step_minutes=60,
)
events = feed.generate_batch(50)
```

### Determinism Guarantee

Two runs with the same `seed` produce **byte-identical** events — same headlines, timestamps, importance scores.

---

## FeedManager

Async coordinator that polls all configured feeds at their intervals.

```python
manager = FeedManager(feed_configs=config.feeds)
await manager.start()   # Start polling loop
events = await manager.poll()  # Manual single poll
await manager.stop()    # Stop polling loop
```

The manager handles:
- Creating the right feed type per config entry
- Respecting `poll_interval_seconds` per feed
- Aggregating events from all feeds into a single list
- Filtering out disabled feeds (`enabled: false`)
