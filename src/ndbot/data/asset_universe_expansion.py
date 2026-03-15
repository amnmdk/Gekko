"""
Expanded asset universe for cross-asset validation.

Extends the base AssetUniverse with comprehensive cross-market assets:
  - Crypto: BTC, ETH, SOL, AVAX, LINK, FET, RNDR
  - Oil proxies: OIL/USD, USO, XLE (via crypto proxy mapping)
  - AI equities: NVDA, AMD, MSFT, GOOGL, META (via proxy)
  - Semiconductor ETFs: SOXX, SMH (via proxy)
  - Macro: DXY proxy, GOLD proxy

For v1, all assets trade via crypto pairs on CCXT.
The mapping layer translates sector exposure to tradeable symbols.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..data_pipeline.universe import Asset, AssetClass, AssetUniverse

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetMapping:
    """Maps a real-world asset to a tradeable crypto proxy."""
    real_symbol: str
    real_asset_class: AssetClass
    proxy_symbol: str
    correlation_note: str = ""
    sector: str = ""


class ExpandedAssetUniverse(AssetUniverse):
    """
    Extended universe with cross-asset proxy mappings.

    Supports testing event signals across multiple markets
    even when only crypto trading is available.
    """

    # Cross-asset proxy mappings
    CROSS_ASSET_PROXIES: list[CrossAssetMapping] = [
        # Oil proxies
        CrossAssetMapping(
            "CL=F", AssetClass.FUTURES, "BTC/USDT",
            "BTC correlates with risk-on/off macro", "energy",
        ),
        CrossAssetMapping(
            "XLE", AssetClass.ETF, "ETH/USDT",
            "ETH as risk proxy for energy sector", "energy",
        ),
        # AI / Tech proxies
        CrossAssetMapping(
            "NVDA", AssetClass.EQUITY, "FET/USDT",
            "FET tracks AI sentiment", "ai",
        ),
        CrossAssetMapping(
            "AMD", AssetClass.EQUITY, "RNDR/USDT",
            "RNDR tracks GPU compute demand", "ai",
        ),
        CrossAssetMapping(
            "MSFT", AssetClass.EQUITY, "ETH/USDT",
            "ETH as tech-sector beta proxy", "ai",
        ),
        CrossAssetMapping(
            "GOOGL", AssetClass.EQUITY, "ETH/USDT",
            "ETH as big-tech proxy", "ai",
        ),
        # Semiconductor proxies
        CrossAssetMapping(
            "SOXX", AssetClass.ETF, "SOL/USDT",
            "SOL as high-beta tech proxy", "semiconductors",
        ),
        CrossAssetMapping(
            "SMH", AssetClass.ETF, "AVAX/USDT",
            "AVAX as alt-tech proxy", "semiconductors",
        ),
        # Macro proxies
        CrossAssetMapping(
            "GLD", AssetClass.ETF, "BTC/USDT",
            "BTC as digital gold proxy", "macro",
        ),
        CrossAssetMapping(
            "DXY", AssetClass.FOREX, "BTC/USDT",
            "BTC inverse DXY correlation", "macro",
        ),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._proxy_map: dict[str, CrossAssetMapping] = {}

    def load_expanded(self) -> None:
        """Load the full expanded universe with proxy mappings."""
        # Load base crypto assets
        self.load_defaults()

        # Add additional crypto assets for proxy trading
        extra = [
            Asset("FET/USDT", AssetClass.CRYPTO, "binance", "FET", "USDT"),
            Asset("RNDR/USDT", AssetClass.CRYPTO, "binance", "RNDR", "USDT"),
            Asset("AAVE/USDT", AssetClass.CRYPTO, "binance", "AAVE", "USDT"),
        ]
        for asset in extra:
            self.add(asset)

        # Register proxy mappings
        for mapping in self.CROSS_ASSET_PROXIES:
            self._proxy_map[mapping.real_symbol] = mapping

        logger.info(
            "Expanded universe: %d tradeable + %d proxy mappings",
            len(self.active_symbols), len(self._proxy_map),
        )

    def get_proxy(self, real_symbol: str) -> str | None:
        """Get tradeable crypto proxy for a real-world symbol."""
        mapping = self._proxy_map.get(real_symbol)
        return mapping.proxy_symbol if mapping else None

    def get_sector_assets(self, sector: str) -> list[str]:
        """Get all tradeable symbols for a sector (via proxy)."""
        symbols = set()
        for m in self.CROSS_ASSET_PROXIES:
            if m.sector == sector.lower():
                symbols.add(m.proxy_symbol)
        # Also add from base sector proxies
        symbols.update(self.by_sector(sector))
        return sorted(symbols)

    def validate_cross_asset(
        self, event_domain: str
    ) -> list[str]:
        """
        Given an event domain, return the list of symbols
        that should be tested for cross-asset signal validity.
        """
        domain_sector_map = {
            "ENERGY_GEO": ["energy", "macro"],
            "AI_RELEASES": ["ai", "semiconductors"],
            "MACRO_INTEREST_RATE": ["macro"],
            "MACRO_INFLATION": ["macro", "energy"],
        }
        sectors = domain_sector_map.get(event_domain, ["macro"])
        symbols: set[str] = set()
        for sector in sectors:
            symbols.update(self.get_sector_assets(sector))
        return sorted(symbols)

    def proxy_mappings_summary(self) -> list[dict]:
        """Return a summary of all proxy mappings."""
        return [
            {
                "real_symbol": m.real_symbol,
                "asset_class": m.real_asset_class.value,
                "proxy": m.proxy_symbol,
                "sector": m.sector,
                "note": m.correlation_note,
            }
            for m in self.CROSS_ASSET_PROXIES
        ]
