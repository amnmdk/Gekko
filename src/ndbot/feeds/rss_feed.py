"""
Async RSS/Atom feed reader.
Uses feedparser for parsing; aiohttp for fetching.
Implements exponential backoff retry on transient HTTP / network errors.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser

from .base import BaseFeed, EventDomain, NewsEvent

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Retry policy: up to 3 attempts with exponential backoff (2s, 4s, 8s)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class RSSFeed(BaseFeed):
    """
    Poll an RSS/Atom feed URL and return new NewsEvent objects.

    feedparser handles malformed XML gracefully — no need for
    BeautifulSoup or extra parsing libraries.
    """

    def __init__(
        self,
        name: str,
        url: str,
        domain: EventDomain,
        credibility_weight: float = 1.0,
    ):
        super().__init__(name=name, domain=domain, credibility_weight=credibility_weight)
        self.url = url

    async def poll(self) -> list[NewsEvent]:
        raw_xml = await self._fetch()
        if raw_xml is None:
            return []
        parsed = feedparser.parse(raw_xml)
        events: list[NewsEvent] = []
        for entry in parsed.entries:
            ev = self._entry_to_event(entry)
            if ev and self._is_new(ev.event_id):
                events.append(ev)
        return events

    async def _fetch(self) -> Optional[str]:
        """Fetch feed XML with exponential backoff retry on transient errors."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                    async with session.get(
                        self.url,
                        headers={"User-Agent": "ndbot/0.1 RSS reader"},
                    ) as resp:
                        if resp.status == 200:
                            return await resp.text()
                        # 429 Too Many Requests — back off and retry
                        if resp.status == 429 and attempt < _MAX_RETRIES:
                            wait = _BACKOFF_BASE ** attempt
                            logger.warning(
                                "Feed %s rate-limited (HTTP 429), retry %d/%d in %.0fs",
                                self.name, attempt, _MAX_RETRIES, wait,
                            )
                            await asyncio.sleep(wait)
                            continue
                        # Non-retryable HTTP error
                        logger.warning(
                            "Feed %s returned HTTP %s (attempt %d/%d)",
                            self.name, resp.status, attempt, _MAX_RETRIES,
                        )
                        return None
            except asyncio.TimeoutError:
                wait = _BACKOFF_BASE ** attempt
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Feed %s timed out (attempt %d/%d), retrying in %.0fs",
                        self.name, attempt, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Feed %s timed out after %d attempts", self.name, _MAX_RETRIES)
            except aiohttp.ClientError as exc:
                wait = _BACKOFF_BASE ** attempt
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "Feed %s network error: %s (attempt %d/%d), retrying in %.0fs",
                        self.name, exc, attempt, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Feed %s failed after %d attempts: %s", self.name, _MAX_RETRIES, exc
                    )
            except Exception as exc:
                # Non-retryable unexpected error
                logger.error("Feed %s unexpected error: %s", self.name, exc)
                return None
        return None

    def _entry_to_event(self, entry: feedparser.FeedParserDict) -> Optional[NewsEvent]:
        headline = getattr(entry, "title", "").strip()
        if not headline:
            return None

        url = getattr(entry, "link", "")
        summary = getattr(entry, "summary", getattr(entry, "description", ""))
        if hasattr(summary, "strip"):
            summary = summary.strip()

        event_id = NewsEvent.make_id(self.name, url, headline)

        published_at = datetime.now(timezone.utc)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published_at = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        tags = [tag.get("term", "") for tag in getattr(entry, "tags", [])]

        return NewsEvent(
            event_id=event_id,
            domain=self.domain,
            headline=headline,
            summary=summary,
            source=self.name,
            url=url,
            published_at=published_at,
            credibility_weight=self.credibility_weight,
            raw_tags=tags,
        )
