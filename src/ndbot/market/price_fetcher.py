"""
Live price fetcher using ccxt async API.

Fetches real-time BTC/USDT and ETH/USDT prices from public exchange APIs.
No API key required — uses public ticker endpoints.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT"]


class LivePriceFetcher:
    """Async price fetcher backed by ccxt."""

    def __init__(
        self,
        exchange_id: str = "binance",
        symbols: Optional[list[str]] = None,
    ):
        self._exchange_id = exchange_id
        self._symbols = symbols or list(_DEFAULT_SYMBOLS)
        self._exchange = None  # Lazy init

    async def _get_exchange(self):
        """Lazy-init the ccxt async exchange instance."""
        if self._exchange is None:
            try:
                import ccxt.async_support as ccxt_async

                exchange_cls = getattr(ccxt_async, self._exchange_id, None)
                if exchange_cls is None:
                    logger.error("Unknown exchange: %s", self._exchange_id)
                    return None
                self._exchange = exchange_cls({"enableRateLimit": True})
            except ImportError:
                logger.warning("ccxt not installed — price fetching unavailable")
                return None
            except Exception as exc:
                logger.warning("Failed to init exchange %s: %s", self._exchange_id, exc)
                return None
        return self._exchange

    async def fetch_prices(self) -> dict[str, float]:
        """
        Fetch current prices for all configured symbols.

        Returns:
            Dict mapping symbol → last price, e.g. {"BTC/USDT": 84321.50}.
            Returns empty dict on any failure (caller should use fallback).
        """
        exchange = await self._get_exchange()
        if exchange is None:
            return {}

        prices: dict[str, float] = {}
        for symbol in self._symbols:
            try:
                ticker = await exchange.fetch_ticker(symbol)
                last = ticker.get("last")
                if last is not None:
                    prices[symbol] = float(last)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", symbol, exc)

        if prices:
            logger.debug("Live prices: %s", prices)
        return prices

    async def close(self) -> None:
        """Close the exchange session."""
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:
                pass
            self._exchange = None
