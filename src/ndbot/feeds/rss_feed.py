"""
Async RSS/Atom feed reader.
Uses feedparser for parsing; aiohttp for fetching.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import aiohttp
import feedparser

from .base import BaseFeed, EventDomain, NewsEvent

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)


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
        try:
            async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
                async with session.get(
                    self.url,
                    headers={"User-Agent": "ndbot/0.1 RSS reader"},
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Feed %s returned HTTP %s", self.name, resp.status)
                        return None
                    return await resp.text()
        except asyncio.TimeoutError:
            logger.warning("Feed %s timed out", self.name)
        except Exception as exc:
            logger.warning("Feed %s fetch error: %s", self.name, exc)
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
