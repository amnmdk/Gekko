"""
Large Historical News Corpus (Step 1).

Builds and manages a large-scale historical news dataset suitable
for statistical alpha research:

  Sources:
    1. RSS feed archives (configurable feed list)
    2. Financial news APIs (NewsAPI, GDELT, etc.)
    3. Social media signals (sentiment proxies)
    4. Regulatory filings and press releases

  Storage per record:
    - headline, body, timestamp, source, url
    - entities (org, person, location)
    - event taxonomy category
    - sentiment score
    - topic embedding vector
    - credibility weight
    - importance score

  Capabilities:
    - Incremental ingest with deduplication
    - Date-range queries with filtering
    - Corpus statistics and coverage reports
    - Export to pandas DataFrame
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default RSS sources for financial news
DEFAULT_RSS_SOURCES: list[dict[str, str]] = [
    {"name": "reuters_markets", "url": "https://www.reuters.com/markets/rss"},
    {"name": "bloomberg_markets", "url": "https://www.bloomberg.com/feed"},
    {"name": "ft_markets", "url": "https://www.ft.com/rss/markets"},
    {"name": "wsj_markets", "url": "https://feeds.wsj.com/wsj/xml/rss/3_7031.xml"},
    {"name": "cnbc_world", "url": "https://www.cnbc.com/id/100727362/device/rss"},
    {"name": "economist", "url": "https://www.economist.com/rss"},
    {"name": "zerohedge", "url": "https://feeds.feedburner.com/zerohedge/feed"},
    {"name": "coindesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss"},
]


@dataclass
class NewsRecord:
    """A single news corpus record with full metadata."""

    record_id: str
    headline: str
    body: str = ""
    timestamp: str = ""
    source: str = ""
    url: str = ""
    entities: dict[str, list[str]] = field(default_factory=dict)
    event_type: str = "UNKNOWN"
    domain: str = "UNKNOWN"
    sentiment_score: float = 0.0
    importance_score: float = 0.5
    credibility_weight: float = 1.0
    topic_embedding: list[float] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    language: str = "en"
    word_count: int = 0
    is_duplicate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorpusStats:
    """Statistics for the news corpus."""

    total_records: int = 0
    unique_sources: int = 0
    date_range_start: str = ""
    date_range_end: str = ""
    records_by_source: dict[str, int] = field(default_factory=dict)
    records_by_domain: dict[str, int] = field(default_factory=dict)
    records_by_event_type: dict[str, int] = field(default_factory=dict)
    avg_sentiment: float = 0.0
    avg_importance: float = 0.0
    duplicates_removed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class NewsCorpus:
    """
    Large-scale historical news dataset for quant research.

    Usage:
        corpus = NewsCorpus()
        corpus.ingest_records([record1, record2, ...])
        records = corpus.query(
            start="2024-01-01", end="2024-12-31",
            domains=["ENERGY_GEO"],
        )
        stats = corpus.compute_stats()
    """

    def __init__(self, storage_dir: str = "data/news_corpus") -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._index: dict[str, dict] = {}
        self._records: list[NewsRecord] = []
        self._seen_hashes: set[str] = set()
        self._load_index()

    def _load_index(self) -> None:
        """Load corpus index from disk."""
        if self._index_path.exists():
            try:
                with open(self._index_path, encoding="utf-8") as f:
                    self._index = json.load(f)
                self._seen_hashes = set(self._index.keys())
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def _save_index(self) -> None:
        """Persist corpus index."""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=1, default=str)

    @staticmethod
    def _hash_record(headline: str, source: str, timestamp: str) -> str:
        """Deterministic hash for deduplication."""
        raw = f"{headline.lower().strip()}|{source}|{timestamp[:16]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def ingest_records(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Ingest a batch of news records with deduplication.

        Returns dict with counts: ingested, duplicates, errors.
        """
        counts = {"ingested": 0, "duplicates": 0, "errors": 0}

        for raw in records:
            try:
                headline = raw.get("headline", "").strip()
                if not headline:
                    counts["errors"] += 1
                    continue

                source = raw.get("source", "unknown")
                ts = raw.get("timestamp", datetime.now(timezone.utc).isoformat())
                rec_hash = self._hash_record(headline, source, ts)

                if rec_hash in self._seen_hashes:
                    counts["duplicates"] += 1
                    continue

                record = NewsRecord(
                    record_id=rec_hash,
                    headline=headline,
                    body=raw.get("body", ""),
                    timestamp=ts,
                    source=source,
                    url=raw.get("url", ""),
                    entities=raw.get("entities", {}),
                    event_type=raw.get("event_type", "UNKNOWN"),
                    domain=raw.get("domain", "UNKNOWN"),
                    sentiment_score=float(raw.get("sentiment_score", 0.0)),
                    importance_score=float(raw.get("importance_score", 0.5)),
                    credibility_weight=float(
                        raw.get("credibility_weight", 1.0)
                    ),
                    topic_embedding=raw.get("topic_embedding", []),
                    keywords=raw.get("keywords", []),
                    language=raw.get("language", "en"),
                    word_count=len(headline.split()) + len(
                        raw.get("body", "").split()
                    ),
                )

                self._records.append(record)
                self._seen_hashes.add(rec_hash)
                self._index[rec_hash] = {
                    "headline": headline[:120],
                    "source": source,
                    "timestamp": ts,
                    "domain": record.domain,
                    "event_type": record.event_type,
                }
                counts["ingested"] += 1

            except (ValueError, KeyError, TypeError) as exc:
                logger.debug("Record ingest error: %s", exc)
                counts["errors"] += 1

        if counts["ingested"] > 0:
            self._save_index()
            self._persist_batch(self._records[-counts["ingested"]:])

        logger.info(
            "Corpus ingest: %d ingested, %d duplicates, %d errors",
            counts["ingested"], counts["duplicates"], counts["errors"],
        )
        return counts

    def _persist_batch(self, records: list[NewsRecord]) -> None:
        """Save a batch of records to a JSONL shard file."""
        shard = self._dir / f"shard_{len(list(self._dir.glob('shard_*.jsonl')))}.jsonl"
        with open(shard, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec.to_dict(), default=str) + "\n")

    def query(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        domains: Optional[list[str]] = None,
        event_types: Optional[list[str]] = None,
        sources: Optional[list[str]] = None,
        min_importance: float = 0.0,
        limit: int = 10000,
    ) -> list[NewsRecord]:
        """Query corpus with filters."""
        results: list[NewsRecord] = []

        for rec in self._records:
            if start and rec.timestamp < start:
                continue
            if end and rec.timestamp > end:
                continue
            if domains and rec.domain not in domains:
                continue
            if event_types and rec.event_type not in event_types:
                continue
            if sources and rec.source not in sources:
                continue
            if rec.importance_score < min_importance:
                continue

            results.append(rec)
            if len(results) >= limit:
                break

        return results

    def load_all(self) -> list[NewsRecord]:
        """Load all records from shard files on disk."""
        if self._records:
            return self._records

        records: list[NewsRecord] = []
        for shard in sorted(self._dir.glob("shard_*.jsonl")):
            with open(shard, encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        records.append(NewsRecord(**{
                            k: data[k] for k in data
                            if k in NewsRecord.__dataclass_fields__
                        }))
                    except (json.JSONDecodeError, TypeError):
                        continue

        self._records = records
        return records

    def compute_stats(self) -> CorpusStats:
        """Compute corpus statistics."""
        records = self._records or self.load_all()
        if not records:
            return CorpusStats()

        sources: dict[str, int] = {}
        domains: dict[str, int] = {}
        event_types: dict[str, int] = {}
        sentiments: list[float] = []
        importances: list[float] = []
        timestamps: list[str] = []

        for rec in records:
            sources[rec.source] = sources.get(rec.source, 0) + 1
            domains[rec.domain] = domains.get(rec.domain, 0) + 1
            event_types[rec.event_type] = (
                event_types.get(rec.event_type, 0) + 1
            )
            sentiments.append(rec.sentiment_score)
            importances.append(rec.importance_score)
            if rec.timestamp:
                timestamps.append(rec.timestamp)

        timestamps.sort()

        return CorpusStats(
            total_records=len(records),
            unique_sources=len(sources),
            date_range_start=timestamps[0] if timestamps else "",
            date_range_end=timestamps[-1] if timestamps else "",
            records_by_source=sources,
            records_by_domain=domains,
            records_by_event_type=event_types,
            avg_sentiment=float(np.mean(sentiments)) if sentiments else 0.0,
            avg_importance=(
                float(np.mean(importances)) if importances else 0.0
            ),
            duplicates_removed=len(self._seen_hashes) - len(records),
        )

    def generate_synthetic_corpus(
        self,
        n_records: int = 5000,
        seed: int = 42,
    ) -> list[NewsRecord]:
        """
        Generate a synthetic news corpus for research and testing.

        Creates realistic-looking records with proper distributions
        of sources, domains, sentiment, and importance.
        """
        rng = np.random.default_rng(seed)

        domains = ["ENERGY_GEO", "AI_RELEASES", "MACRO", "CRYPTO", "EQUITY"]
        sources = [
            "reuters", "bloomberg", "ft", "wsj", "cnbc",
            "coindesk", "techcrunch", "arxiv",
        ]
        event_types = [
            "SUPPLY_DISRUPTION", "POLICY_CHANGE", "PRODUCT_LAUNCH",
            "EARNINGS", "REGULATORY", "CONFLICT", "INFRASTRUCTURE",
            "FUNDING", "PARTNERSHIP", "INCIDENT",
        ]
        headline_templates = [
            "{org} Announces Major {action} in {region}",
            "Breaking: {event} Impacts {sector} Markets",
            "{org} Reports {metric} {direction} in Q{quarter}",
            "New {policy} Regulation Proposed by {regulator}",
            "{region} {commodity} Supply Disrupted by {cause}",
            "AI {product} Launch by {org} Exceeds Expectations",
            "{org} Raises ${amount}B in Series {round} Funding",
            "Global {commodity} Prices {direction} After {event}",
        ]

        orgs = [
            "OPEC", "Tesla", "OpenAI", "Anthropic", "Google",
            "JPMorgan", "Goldman Sachs", "Meta", "NVIDIA", "Saudi Aramco",
        ]
        regions = [
            "Middle East", "Asia Pacific", "Europe", "North America",
            "Latin America",
        ]
        commodities = ["Oil", "Gas", "Gold", "Copper", "Lithium"]

        records: list[NewsRecord] = []
        base_ts = datetime(2023, 1, 1, tzinfo=timezone.utc)

        for i in range(n_records):
            template = rng.choice(headline_templates)
            headline = template.format(
                org=rng.choice(orgs),
                action=rng.choice(["Expansion", "Restructuring", "Deal"]),
                region=rng.choice(regions),
                event=rng.choice(["Conflict", "Policy Shift", "Discovery"]),
                sector=rng.choice(["Energy", "Tech", "Finance"]),
                metric=rng.choice(["Revenue", "Earnings", "Growth"]),
                direction=rng.choice(["Up", "Down", "Surge", "Drop"]),
                quarter=rng.integers(1, 5),
                policy=rng.choice(["AI", "Energy", "Trade", "Crypto"]),
                regulator=rng.choice(["SEC", "EU", "FCA", "CFTC"]),
                commodity=rng.choice(commodities),
                cause=rng.choice(["Conflict", "Weather", "Strike"]),
                product=rng.choice(["Model", "Platform", "Chip"]),
                amount=rng.integers(1, 20),
                round=rng.choice(["A", "B", "C", "D", "E"]),
            )

            ts = base_ts.replace(
                month=max(1, min(12, 1 + i * 12 // n_records)),
                day=max(1, min(28, 1 + i % 28)),
                hour=int(rng.integers(6, 22)),
                minute=int(rng.integers(0, 60)),
            )

            domain = str(rng.choice(domains))
            sentiment = float(rng.normal(0.0, 0.4))
            sentiment = max(-1.0, min(1.0, sentiment))

            record = NewsRecord(
                record_id=f"syn_{i:06d}",
                headline=headline,
                body=f"Detailed analysis of {headline.lower()}.",
                timestamp=ts.isoformat(),
                source=str(rng.choice(sources)),
                url=f"https://news.example.com/{i}",
                entities={
                    "organizations": [str(rng.choice(orgs))],
                    "locations": [str(rng.choice(regions))],
                },
                event_type=str(rng.choice(event_types)),
                domain=domain,
                sentiment_score=sentiment,
                importance_score=float(rng.beta(2, 5)),
                credibility_weight=float(rng.uniform(0.5, 1.0)),
                topic_embedding=[float(x) for x in rng.normal(0, 1, 32)],
                keywords=[headline.split()[0].lower()],
                word_count=len(headline.split()) + 20,
            )
            records.append(record)

        logger.info("Generated synthetic corpus: %d records", n_records)
        return records

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def sources_config(self) -> list[dict[str, str]]:
        return DEFAULT_RSS_SOURCES
