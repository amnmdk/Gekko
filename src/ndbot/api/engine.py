"""
Mock trading engine that runs as a background asyncio task.

Every ~25 seconds it:
  1. Generates a synthetic news event from one of the two domains
  2. Runs classifier → confidence model → signal generator
  3. If confidence is high enough, opens a paper position
  4. Updates open positions (simulated price movement + SL/TP/expiry checks)
  5. Broadcasts all state changes via WebSocket

The simulated prices react to event sentiment so P&L actually moves.
Starting balance: configurable, default €500.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone

from ..classifier.keyword_classifier import KeywordClassifier
from ..feeds.base import EventDomain, NewsEvent
from ..feeds.synthetic import SyntheticFeed
from ..geo.coordinates import get_event_coordinates
from .state import AppState, EventEntry, TradeEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulated price store (BTC and ETH as proxies)
# ---------------------------------------------------------------------------

_DOMAIN_SYMBOLS: dict[EventDomain, str] = {
    EventDomain.ENERGY_GEO: "BTC/USDT",
    EventDomain.AI_RELEASES: "ETH/USDT",
}

_SL_PCT = 0.020
_TP_PCT = 0.040
_MAX_TICKS = 12


class MockTradingEngine:
    """
    Self-contained mock trading engine.  No external APIs required.
    """

    def __init__(
        self,
        state: AppState,
        tick_interval: float = 25.0,
        seed: int | None = None,
    ):
        self._state = state
        self._tick_interval = tick_interval
        self._rng = random.Random(seed)
        # Prices live in state so REST routes + WS can serve them
        self._state.prices = {"BTC/USDT": 65_000.0, "ETH/USDT": 3_500.0}
        self._position_ticks: dict[str, int] = {}  # trade_id → open tick count
        self._running = False
        self._classifier = KeywordClassifier()
        self._feeds = {
            EventDomain.ENERGY_GEO: SyntheticFeed(
                domain=EventDomain.ENERGY_GEO, events_per_poll=1, seed=seed
            ),
            EventDomain.AI_RELEASES: SyntheticFeed(
                domain=EventDomain.AI_RELEASES, events_per_poll=1, seed=seed
            ),
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._running = True
        self._state.running = True
        logger.info("MockTradingEngine started (balance=%.2f EUR)", self._state.balance)
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Engine tick error: %s", exc)
            interval = float(self._state.config.get("tick_interval", self._tick_interval))
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
        self._state.running = False

    # ------------------------------------------------------------------
    # Core tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        # 1. Pick a domain at random, generate one event
        domain = self._rng.choice([EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES])
        raw_events = await self._feeds[domain].poll()
        if not raw_events:
            # Force-generate one event
            raw_events = self._feeds[domain].generate_batch(1)
        event = raw_events[0]

        # 2. Enrich with classifier (keywords, sentiment adjustment)
        event = self._classifier.enrich(event)

        # 3. Compute simple confidence from importance + sentiment magnitude
        confidence = self._compute_confidence(event)

        # 4. Determine direction from keywords
        direction = self._determine_direction(event)

        # 5. Record event entry
        lat, lon = get_event_coordinates(event)
        entry = EventEntry(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            domain=domain.value,
            headline=event.headline,
            summary=event.summary,
            sentiment=round(event.sentiment_score, 3),
            importance=round(event.importance_score, 3),
            direction=direction,
            confidence=round(confidence, 3),
            lat=lat,
            lon=lon,
        )

        async with self._state._lock:
            self._state.events.insert(0, entry)
            self._state.events = self._state.events[:200]

        await self._state.broadcast({"type": "event", "data": entry.to_dict()})

        # 6. Maybe open a trade
        cfg = self._state.config
        min_conf = float(cfg.get("min_confidence", 0.40))
        max_pos = int(cfg.get("max_positions", 3))
        if (
            direction != "NEUTRAL"
            and confidence >= min_conf
            and len(self._state.open_positions) < max_pos
            and self._state.balance > 20
        ):
            await self._open_trade(event, direction, confidence, lat, lon)

        # 7. Update all open positions (price drift + exit checks)
        await self._update_positions(event)

    # ------------------------------------------------------------------
    # Trade lifecycle
    # ------------------------------------------------------------------

    async def _open_trade(
        self,
        event: NewsEvent,
        direction: str,
        confidence: float,
        lat: float,
        lon: float,
    ) -> None:
        symbol = _DOMAIN_SYMBOLS.get(event.domain, "BTC/USDT")
        price = self._state.prices[symbol]
        risk_pct = float(self._state.config.get("risk_pct", 0.02))
        size_eur = max(5.0, min(50.0, self._state.balance * risk_pct * confidence))
        trade_id = str(uuid.uuid4())[:8]
        trade = TradeEntry(
            id=trade_id,
            opened_at=datetime.now(timezone.utc).isoformat(),
            closed_at=None,
            symbol=symbol,
            direction=direction,
            size_eur=round(size_eur, 2),
            entry_price=round(price, 2),
            exit_price=None,
            pnl_eur=0.0,
            pnl_pct=0.0,
            status="OPEN",
            event_headline=event.headline[:80],
            lat=lat,
            lon=lon,
        )
        async with self._state._lock:
            self._state.open_positions[trade_id] = trade
            self._position_ticks[trade_id] = 0

        logger.info("OPEN %s %s @ %.2f (size=%.2f EUR)", direction, symbol, price, size_eur)
        await self._state.broadcast({"type": "trade_open", "data": trade.to_dict()})

    async def _update_positions(self, latest_event: NewsEvent) -> None:
        """Apply price movement and check SL/TP/expiry for every open position."""
        self._apply_price_shock(latest_event)

        # Broadcast live prices every tick so the UI can show them
        await self._state.broadcast({
            "type": "price_update",
            "data": dict(self._state.prices),
        })

        closed: list[str] = []
        async with self._state._lock:
            for tid, trade in list(self._state.open_positions.items()):
                self._position_ticks[tid] = self._position_ticks.get(tid, 0) + 1
                price = self._state.prices[trade.symbol]
                entry = trade.entry_price
                direction = trade.direction

                # PnL as fraction of entry price move
                if direction == "LONG":
                    price_return = (price - entry) / entry
                else:
                    price_return = (entry - price) / entry

                pnl_eur = round(trade.size_eur * price_return, 2)
                pnl_pct = round(price_return * 100, 2)

                # Determine exit condition
                status = None
                if direction == "LONG":
                    if price <= entry * (1 - _SL_PCT):
                        status = "SL_HIT"
                    elif price >= entry * (1 + _TP_PCT):
                        status = "TP_HIT"
                else:
                    if price >= entry * (1 + _SL_PCT):
                        status = "SL_HIT"
                    elif price <= entry * (1 - _TP_PCT):
                        status = "TP_HIT"

                if status is None and self._position_ticks[tid] >= _MAX_TICKS:  # noqa: E501
                    status = "EXPIRED"

                if status:
                    trade.exit_price = round(price, 2)
                    trade.pnl_eur = pnl_eur
                    trade.pnl_pct = pnl_pct
                    trade.status = status
                    trade.closed_at = datetime.now(timezone.utc).isoformat()
                    # Update balance
                    self._state.balance = round(self._state.balance + pnl_eur, 2)
                    if self._state.balance > self._state.peak_balance:
                        self._state.peak_balance = self._state.balance
                    self._state.total_trades += 1
                    if pnl_eur > 0:
                        self._state.winning_trades += 1
                    self._state.trades.insert(0, trade)
                    self._state.trades = self._state.trades[:500]
                    self._state.record_equity()   # append to equity curve
                    closed.append(tid)
                    logger.info(
                        "CLOSE %s %s (%s) PnL=%.2f EUR | balance=%.2f",
                        trade.direction, trade.symbol, status, pnl_eur, self._state.balance,
                    )
                else:
                    # Just update running PnL
                    trade.pnl_eur = pnl_eur
                    trade.pnl_pct = pnl_pct

            for tid in closed:
                self._state.open_positions.pop(tid, None)
                self._position_ticks.pop(tid, None)

        # Broadcast updates outside lock
        for tid in closed:
            # Find in trades list
            for t in self._state.trades:
                if t.id == tid:
                    await self._state.broadcast({"type": "trade_close", "data": t.to_dict()})
                    break

        if self._state.open_positions:
            positions_data = [p.to_dict() for p in self._state.open_positions.values()]
            await self._state.broadcast({"type": "positions_update", "data": positions_data})

        await self._state.broadcast({"type": "balance_update", "data": self._state.summary()})

    # ------------------------------------------------------------------
    # Price simulation
    # ------------------------------------------------------------------

    def _apply_price_shock(self, event: NewsEvent) -> None:
        symbol = _DOMAIN_SYMBOLS.get(event.domain, "BTC/USDT")
        for sym in self._state.prices:
            # Base random walk: ±0.15 %
            drift = self._rng.gauss(0, 0.0015)
            # Sentiment shock on the relevant symbol only
            if sym == symbol:
                drift += event.sentiment_score * 0.008
            self._state.prices[sym] = round(self._state.prices[sym] * (1 + drift), 2)

    # ------------------------------------------------------------------
    # Signal helpers (lightweight, no full config needed)
    # ------------------------------------------------------------------

    _BEARISH_ENERGY = {
        "attack", "strike", "missile", "drone", "blockade", "closure",
        "sanctions", "embargo", "sabotage", "explosion", "disruption",
        "outage", "halt", "ban", "restriction", "threat", "conflict", "cuts",
    }
    _BULLISH_ENERGY = {
        "ceasefire", "reopens", "resumes", "discovery", "production increase",
        "peace", "normalisation", "lifted", "agreement", "deal",
    }
    _BEARISH_AI = {
        "vulnerability", "jailbreak", "outage", "ban", "regulatory",
        "investigation", "breach", "leak", "fine", "shutdown", "blocked",
    }
    _BULLISH_AI = {
        "releases", "launch", "launches", "open-source", "raises", "funding",
        "achieves", "surpasses", "breakthrough", "wins", "award",
    }

    def _determine_direction(self, event: NewsEvent) -> str:
        text = (event.headline + " " + event.summary).lower()
        if event.domain == EventDomain.ENERGY_GEO:
            bearish = sum(1 for kw in self._BEARISH_ENERGY if kw in text)
            bullish = sum(1 for kw in self._BULLISH_ENERGY if kw in text)
        else:
            bearish = sum(1 for kw in self._BEARISH_AI if kw in text)
            bullish = sum(1 for kw in self._BULLISH_AI if kw in text)

        if bearish > bullish or event.sentiment_score < -0.25:
            return "SHORT"
        if bullish > bearish or event.sentiment_score > 0.25:
            return "LONG"
        return "NEUTRAL"

    def _compute_confidence(self, event: NewsEvent) -> float:
        """Blend importance score + sentiment magnitude into [0, 1]."""
        importance = event.importance_score
        sentiment_strength = abs(event.sentiment_score)
        # Weight: 60 % importance + 40 % sentiment strength
        raw = 0.6 * importance + 0.4 * sentiment_strength
        # Credibility boost for known sources
        raw *= event.credibility_weight
        return min(0.95, max(0.05, round(raw, 4)))


# ===========================================================================
# LIVE TRADING ENGINE — Real news feeds + real exchange prices
# ===========================================================================


class LiveTradingEngine:
    """
    Paper trading engine powered by real RSS news and live exchange prices.

    Same trade lifecycle as MockTradingEngine but with real data:
      - Events come from RSS feeds (BBC, TechCrunch, etc.)
      - Prices come from ccxt (Binance public API)
      - Falls back to synthetic feeds / random walk if network is down
    """

    # Reuse keyword sets from Mock engine
    _BEARISH_ENERGY = MockTradingEngine._BEARISH_ENERGY
    _BULLISH_ENERGY = MockTradingEngine._BULLISH_ENERGY
    _BEARISH_AI = MockTradingEngine._BEARISH_AI
    _BULLISH_AI = MockTradingEngine._BULLISH_AI

    def __init__(
        self,
        state: AppState,
        tick_interval: float = 30.0,
        exchange_id: str = "binance",
    ):
        self._state = state
        self._tick_interval = tick_interval
        self._rng = random.Random()
        self._position_ticks: dict[str, int] = {}
        self._running = False
        self._classifier = KeywordClassifier()

        # Live price fetcher (lazy import to avoid hard ccxt dep)
        from ..market.price_fetcher import LivePriceFetcher

        self._price_fetcher = LivePriceFetcher(
            exchange_id=exchange_id,
            symbols=["BTC/USDT", "ETH/USDT"],
        )

        # RSS feeds per domain
        from ..feeds.defaults import AI_RELEASES_FEEDS, ENERGY_GEO_FEEDS
        from ..feeds.rss_feed import RSSFeed

        self._rss_feeds: dict[EventDomain, list] = {
            EventDomain.ENERGY_GEO: [
                RSSFeed(name=n, url=u, domain=EventDomain.ENERGY_GEO,
                        credibility_weight=w)
                for n, u, w in ENERGY_GEO_FEEDS
            ],
            EventDomain.AI_RELEASES: [
                RSSFeed(name=n, url=u, domain=EventDomain.AI_RELEASES,
                        credibility_weight=w)
                for n, u, w in AI_RELEASES_FEEDS
            ],
        }

        # Synthetic fallbacks for when RSS is empty/down
        self._synthetic = {
            EventDomain.ENERGY_GEO: SyntheticFeed(
                domain=EventDomain.ENERGY_GEO, events_per_poll=1,
            ),
            EventDomain.AI_RELEASES: SyntheticFeed(
                domain=EventDomain.AI_RELEASES, events_per_poll=1,
            ),
        }

        # Init prices with defaults (overwritten on first successful fetch)
        self._state.prices = {"BTC/USDT": 65_000.0, "ETH/USDT": 3_500.0}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._running = True
        self._state.running = True

        # Fetch initial real prices before first tick
        initial_prices = await self._price_fetcher.fetch_prices()
        if initial_prices:
            self._state.prices.update(initial_prices)
            logger.info(
                "LiveEngine started with real prices: %s", initial_prices
            )
        else:
            logger.warning(
                "LiveEngine started — exchange unreachable, using defaults"
            )

        logger.info(
            "LiveTradingEngine started (balance=%.2f EUR, mode=LIVE)",
            self._state.balance,
        )

        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Live engine tick error: %s", exc)
            interval = float(
                self._state.config.get("tick_interval", self._tick_interval)
            )
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
        self._state.running = False

    async def cleanup(self) -> None:
        """Close async resources."""
        await self._price_fetcher.close()

    # ------------------------------------------------------------------
    # Core tick — same structure as Mock but with real data sources
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        # 1. Pick a domain and poll RSS feeds for real news
        domain = self._rng.choice(
            [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]
        )
        event = await self._poll_rss(domain)

        # 2. Enrich with classifier
        event = self._classifier.enrich(event)

        # 3. Confidence + direction
        confidence = self._compute_confidence(event)
        direction = self._determine_direction(event)

        # 4. Record event
        lat, lon = get_event_coordinates(event)
        entry = EventEntry(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            domain=domain.value,
            headline=event.headline,
            summary=event.summary,
            sentiment=round(event.sentiment_score, 3),
            importance=round(event.importance_score, 3),
            direction=direction,
            confidence=round(confidence, 3),
            lat=lat,
            lon=lon,
        )

        async with self._state._lock:
            self._state.events.insert(0, entry)
            self._state.events = self._state.events[:200]

        await self._state.broadcast(
            {"type": "event", "data": entry.to_dict()}
        )

        # 5. Maybe open a trade
        cfg = self._state.config
        min_conf = float(cfg.get("min_confidence", 0.40))
        max_pos = int(cfg.get("max_positions", 3))
        if (
            direction != "NEUTRAL"
            and confidence >= min_conf
            and len(self._state.open_positions) < max_pos
            and self._state.balance > 20
        ):
            await self._open_trade(event, direction, confidence, lat, lon)

        # 6. Fetch real prices and update positions
        await self._update_prices_and_positions(event)

    # ------------------------------------------------------------------
    # RSS feed polling with fallback
    # ------------------------------------------------------------------

    async def _poll_rss(self, domain: EventDomain) -> NewsEvent:
        """Poll all RSS feeds for a domain; fall back to synthetic."""
        all_events: list[NewsEvent] = []
        for feed in self._rss_feeds.get(domain, []):
            try:
                events = await feed.poll()
                all_events.extend(events)
            except Exception as exc:
                logger.debug("RSS feed %s failed: %s", feed.name, exc)

        if all_events:
            # Pick the most recent event
            all_events.sort(
                key=lambda e: e.published_at, reverse=True
            )
            logger.info(
                "LIVE event from RSS: %s", all_events[0].headline[:80]
            )
            return all_events[0]

        # Fallback to synthetic
        logger.debug("No RSS events for %s — using synthetic", domain.value)
        events = await self._synthetic[domain].poll()
        if not events:
            events = self._synthetic[domain].generate_batch(1)
        return events[0]

    # ------------------------------------------------------------------
    # Live price fetching + position updates
    # ------------------------------------------------------------------

    async def _update_prices_and_positions(
        self, latest_event: NewsEvent
    ) -> None:
        """Fetch real prices, then check SL/TP/expiry on open positions."""
        # Try real prices first
        real_prices = await self._price_fetcher.fetch_prices()
        if real_prices:
            self._state.prices.update(real_prices)
        else:
            # Fallback: gentle random walk on last known prices
            self._apply_price_fallback(latest_event)

        # Broadcast prices
        await self._state.broadcast({
            "type": "price_update",
            "data": dict(self._state.prices),
        })

        # Check positions (identical logic to MockTradingEngine)
        closed: list[str] = []
        async with self._state._lock:
            for tid, trade in list(self._state.open_positions.items()):
                self._position_ticks[tid] = (
                    self._position_ticks.get(tid, 0) + 1
                )
                price = self._state.prices[trade.symbol]
                entry_p = trade.entry_price
                d = trade.direction

                if d == "LONG":
                    price_return = (price - entry_p) / entry_p
                else:
                    price_return = (entry_p - price) / entry_p

                pnl_eur = round(trade.size_eur * price_return, 2)
                pnl_pct = round(price_return * 100, 2)

                status = None
                if d == "LONG":
                    if price <= entry_p * (1 - _SL_PCT):
                        status = "SL_HIT"
                    elif price >= entry_p * (1 + _TP_PCT):
                        status = "TP_HIT"
                else:
                    if price >= entry_p * (1 + _SL_PCT):
                        status = "SL_HIT"
                    elif price <= entry_p * (1 - _TP_PCT):
                        status = "TP_HIT"

                if (
                    status is None
                    and self._position_ticks[tid] >= _MAX_TICKS
                ):
                    status = "EXPIRED"

                if status:
                    trade.exit_price = round(price, 2)
                    trade.pnl_eur = pnl_eur
                    trade.pnl_pct = pnl_pct
                    trade.status = status
                    trade.closed_at = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    self._state.balance = round(
                        self._state.balance + pnl_eur, 2
                    )
                    if self._state.balance > self._state.peak_balance:
                        self._state.peak_balance = self._state.balance
                    self._state.total_trades += 1
                    if pnl_eur > 0:
                        self._state.winning_trades += 1
                    self._state.trades.insert(0, trade)
                    self._state.trades = self._state.trades[:500]
                    self._state.record_equity()
                    closed.append(tid)
                    logger.info(
                        "CLOSE %s %s (%s) PnL=%.2f EUR | bal=%.2f",
                        trade.direction, trade.symbol, status,
                        pnl_eur, self._state.balance,
                    )
                else:
                    trade.pnl_eur = pnl_eur
                    trade.pnl_pct = pnl_pct

            for tid in closed:
                self._state.open_positions.pop(tid, None)
                self._position_ticks.pop(tid, None)

        # Broadcast closed trades
        for tid in closed:
            for t in self._state.trades:
                if t.id == tid:
                    await self._state.broadcast(
                        {"type": "trade_close", "data": t.to_dict()}
                    )
                    break

        if self._state.open_positions:
            await self._state.broadcast({
                "type": "positions_update",
                "data": [
                    p.to_dict()
                    for p in self._state.open_positions.values()
                ],
            })

        await self._state.broadcast(
            {"type": "balance_update", "data": self._state.summary()}
        )

    # ------------------------------------------------------------------
    # Trade opening (same as Mock)
    # ------------------------------------------------------------------

    async def _open_trade(
        self,
        event: NewsEvent,
        direction: str,
        confidence: float,
        lat: float,
        lon: float,
    ) -> None:
        symbol = _DOMAIN_SYMBOLS.get(event.domain, "BTC/USDT")
        price = self._state.prices[symbol]
        risk_pct = float(self._state.config.get("risk_pct", 0.02))
        size_eur = max(
            5.0, min(50.0, self._state.balance * risk_pct * confidence)
        )
        trade_id = str(uuid.uuid4())[:8]
        trade = TradeEntry(
            id=trade_id,
            opened_at=datetime.now(timezone.utc).isoformat(),
            closed_at=None,
            symbol=symbol,
            direction=direction,
            size_eur=round(size_eur, 2),
            entry_price=round(price, 2),
            exit_price=None,
            pnl_eur=0.0,
            pnl_pct=0.0,
            status="OPEN",
            event_headline=event.headline[:80],
            lat=lat,
            lon=lon,
        )
        async with self._state._lock:
            self._state.open_positions[trade_id] = trade
            self._position_ticks[trade_id] = 0

        logger.info(
            "OPEN %s %s @ %.2f (size=%.2f EUR) [LIVE]",
            direction, symbol, price, size_eur,
        )
        await self._state.broadcast(
            {"type": "trade_open", "data": trade.to_dict()}
        )

    # ------------------------------------------------------------------
    # Price fallback (used when exchange is unreachable)
    # ------------------------------------------------------------------

    def _apply_price_fallback(self, event: NewsEvent) -> None:
        """Gentle random walk — only used when live prices fail."""
        symbol = _DOMAIN_SYMBOLS.get(event.domain, "BTC/USDT")
        for sym in self._state.prices:
            drift = self._rng.gauss(0, 0.0008)  # Smaller than mock
            if sym == symbol:
                drift += event.sentiment_score * 0.004
            self._state.prices[sym] = round(
                self._state.prices[sym] * (1 + drift), 2
            )

    # ------------------------------------------------------------------
    # Signal helpers (same logic as Mock)
    # ------------------------------------------------------------------

    def _determine_direction(self, event: NewsEvent) -> str:
        text = (event.headline + " " + event.summary).lower()
        if event.domain == EventDomain.ENERGY_GEO:
            bearish = sum(
                1 for kw in self._BEARISH_ENERGY if kw in text
            )
            bullish = sum(
                1 for kw in self._BULLISH_ENERGY if kw in text
            )
        else:
            bearish = sum(1 for kw in self._BEARISH_AI if kw in text)
            bullish = sum(1 for kw in self._BULLISH_AI if kw in text)

        if bearish > bullish or event.sentiment_score < -0.25:
            return "SHORT"
        if bullish > bearish or event.sentiment_score > 0.25:
            return "LONG"
        return "NEUTRAL"

    def _compute_confidence(self, event: NewsEvent) -> float:
        importance = event.importance_score
        sentiment_strength = abs(event.sentiment_score)
        raw = 0.6 * importance + 0.4 * sentiment_strength
        raw *= event.credibility_weight
        return min(0.95, max(0.05, round(raw, 4)))
