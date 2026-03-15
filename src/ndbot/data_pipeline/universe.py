"""
Asset Universe — multi-asset abstraction layer.

Supports:
  - Crypto (via CCXT)
  - Equities (via symbol mapping)
  - Futures
  - ETFs

Even if v1 uses crypto proxies, the abstraction is in place
for future multi-asset expansion.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AssetClass(str, Enum):
    CRYPTO = "CRYPTO"
    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    ETF = "ETF"
    FOREX = "FOREX"


@dataclass
class Asset:
    """A single tradeable asset."""
    symbol: str
    asset_class: AssetClass
    exchange: str = ""
    base_currency: str = ""
    quote_currency: str = "USD"
    min_lot_size: float = 0.0001
    tick_size: float = 0.01
    commission_rate: float = 0.001
    active: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.symbol} ({self.asset_class.value})"


class AssetUniverse:
    """
    Manages the set of tradeable assets.

    Prevents survivorship bias by maintaining both active
    and delisted assets when doing historical analysis.
    """

    # Default crypto proxy mappings for sector analysis
    SECTOR_PROXIES: dict[str, list[str]] = {
        "energy": ["BTC/USDT", "ETH/USDT"],
        "ai": ["FET/USDT", "RNDR/USDT", "ETH/USDT"],
        "defi": ["UNI/USDT", "AAVE/USDT", "LINK/USDT"],
        "infrastructure": ["DOT/USDT", "AVAX/USDT", "SOL/USDT"],
    }

    def __init__(self) -> None:
        self._assets: dict[str, Asset] = {}
        self._delisted: dict[str, Asset] = {}

    def add(self, asset: Asset) -> None:
        """Add an asset to the universe."""
        self._assets[asset.symbol] = asset

    def remove(self, symbol: str) -> None:
        """Move an asset to the delisted set (survivorship-bias aware)."""
        if symbol in self._assets:
            asset = self._assets.pop(symbol)
            asset.active = False
            self._delisted[symbol] = asset
            logger.info("Asset delisted: %s", symbol)

    def get(self, symbol: str) -> Optional[Asset]:
        """Look up an asset by symbol (active only)."""
        return self._assets.get(symbol)

    def get_including_delisted(self, symbol: str) -> Optional[Asset]:
        """Look up an asset including delisted (for backtest/research)."""
        return self._assets.get(symbol) or self._delisted.get(symbol)

    @property
    def active_symbols(self) -> list[str]:
        """All currently active symbols."""
        return [s for s, a in self._assets.items() if a.active]

    @property
    def all_symbols(self) -> list[str]:
        """All symbols including delisted (for survivorship-bias-free research)."""
        return list(self._assets.keys()) + list(self._delisted.keys())

    def by_class(self, asset_class: AssetClass) -> list[Asset]:
        """Filter active assets by class."""
        return [a for a in self._assets.values() if a.asset_class == asset_class and a.active]

    def by_sector(self, sector: str) -> list[str]:
        """Get proxy symbols for a sector."""
        return self.SECTOR_PROXIES.get(sector.lower(), [])

    def load_defaults(self) -> None:
        """Load default crypto trading universe."""
        defaults = [
            Asset("BTC/USDT", AssetClass.CRYPTO, "binance", "BTC", "USDT"),
            Asset("ETH/USDT", AssetClass.CRYPTO, "binance", "ETH", "USDT"),
            Asset("SOL/USDT", AssetClass.CRYPTO, "binance", "SOL", "USDT"),
            Asset("AVAX/USDT", AssetClass.CRYPTO, "binance", "AVAX", "USDT"),
            Asset("LINK/USDT", AssetClass.CRYPTO, "binance", "LINK", "USDT"),
            Asset("DOT/USDT", AssetClass.CRYPTO, "binance", "DOT", "USDT"),
            Asset("UNI/USDT", AssetClass.CRYPTO, "binance", "UNI", "USDT"),
        ]
        for asset in defaults:
            self.add(asset)
        logger.info("Loaded %d default assets", len(defaults))

    def to_list(self) -> list[dict]:
        """Serialise the universe."""
        return [
            {
                "symbol": a.symbol,
                "asset_class": a.asset_class.value,
                "exchange": a.exchange,
                "active": a.active,
            }
            for a in self._assets.values()
        ]
