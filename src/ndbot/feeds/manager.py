"""
Feed manager: orchestrates multiple feeds and dispatches events to handlers.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from ..config.settings import BotConfig
from .base import BaseFeed, EventDomain, NewsEvent
from .rss_feed import RSSFeed

logger = logging.getLogger(__name__)

EventHandler = Callable[[NewsEvent], Awaitable[None]]


class FeedManager:
    """
    Manages a collection of feeds and dispatches NewsEvent objects
    to registered async handlers.

    Usage
    -----
    mgr = FeedManager(config)
    mgr.on_event(my_handler)
    await mgr.run()   # runs until cancelled
    """

    def __init__(self, config: BotConfig):
        self._config = config
        self._feeds: list[tuple[BaseFeed, int]] = []  # (feed, poll_interval_seconds)
        self._handlers: list[EventHandler] = []
        self._running = False
        self._build_feeds()

    def _build_feeds(self) -> None:
        """Instantiate RSS feeds from config and register them."""
        for fc in self._config.feeds:
            if not fc.enabled:
                continue
            domain = EventDomain(fc.domain)
            feed = RSSFeed(
                name=fc.name,
                url=fc.url,
                domain=domain,
                credibility_weight=fc.credibility_weight,
            )
            self._feeds.append((feed, fc.poll_interval_seconds))
            logger.info("Registered RSS feed: %s (%s)", fc.name, fc.domain)

    def add_feed(self, feed: BaseFeed, poll_interval_seconds: int = 60) -> None:
        """Programmatically add a feed (e.g. synthetic feed for simulate mode)."""
        self._feeds.append((feed, poll_interval_seconds))
        logger.info("Added feed: %s", feed.name)

    def on_event(self, handler: EventHandler) -> None:
        """Register an async handler function for incoming events."""
        self._handlers.append(handler)

    async def run(self) -> None:
        """Run all feed pollers concurrently until cancelled."""
        self._running = True
        tasks = [
            asyncio.create_task(self._poll_loop(feed, interval), name=f"feed:{feed.name}")
            for feed, interval in self._feeds
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        finally:
            self._running = False

    async def _poll_loop(self, feed: BaseFeed, interval: int) -> None:
        """Continuously poll *feed* every *interval* seconds."""
        logger.debug("Starting poll loop for %s (interval=%ds)", feed.name, interval)
        while True:
            try:
                events = await feed.poll()
                for ev in events:
                    await self._dispatch(ev)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — must not crash poll loop
                logger.error("Feed %s poll error: %s", feed.name, exc)
            await asyncio.sleep(interval)

    async def _dispatch(self, event: NewsEvent) -> None:
        """Dispatch event to all registered handlers."""
        logger.info("[EVENT] %s | %s | %s", event.domain.value, event.source, event.headline[:80])
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception as exc:  # noqa: BLE001 — handler must not crash dispatch
                logger.error("Handler error for %s: %s", type(handler).__name__, exc)

    async def poll_once(self) -> list[NewsEvent]:
        """Poll all feeds exactly once and return collected events (no dispatch)."""
        all_events: list[NewsEvent] = []
        for feed, _ in self._feeds:
            try:
                events = await feed.poll()
                all_events.extend(events)
            except Exception as exc:  # noqa: BLE001 — one feed failure must not block others
                logger.error("Feed %s one-shot poll error: %s", feed.name, exc)
        return all_events
