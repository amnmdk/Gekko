"""
Market data feed abstraction.

In simulate/backtest mode: serves from in-memory DataFrame (synthetic or stored).
In paper mode: wraps CCXT exchange API for live candle fetching.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..config.settings import BotConfig, MarketConfig
from .regime import RegimeDetector, VolatilityRegime
from .synthetic_candles import SyntheticCandleGenerator

logger = logging.getLogger(__name__)


class MarketDataFeed:
    """
    Unified market data interface.

    Maintains a rolling candle buffer in memory.
    Provides current price, OHLCV window, and regime state.
    """

    def __init__(self, config: BotConfig):
        self._config = config
        self._mc: MarketConfig = config.market
        self._regime = RegimeDetector(
            atr_period=self._mc.atr_period,
            atr_percentile_window=self._mc.atr_percentile_window,
            ma_short=self._mc.ma_short,
            ma_long=self._mc.ma_long,
        )
        self._candles: pd.DataFrame = pd.DataFrame()
        self._exchange = None  # CCXT exchange instance (paper mode only)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def load_synthetic(
        self,
        n_candles: int = 500,
        start_price: float = 45_000.0,
        seed: int = 42,
        shock_times: Optional[list[datetime]] = None,
    ) -> None:
        """Load synthetic candle data for simulate/backtest mode."""
        gen = SyntheticCandleGenerator(
            symbol=self._mc.symbol,
            start_price=start_price,
            timeframe_minutes=self._tf_minutes(),
            seed=seed,
        )
        raw = gen.generate(n_candles, shock_times=shock_times)
        self._candles = self._regime.add_indicators(raw)
        logger.info(
            "Loaded %d synthetic candles for %s [%s → %s]",
            len(self._candles),
            self._mc.symbol,
            self._candles.index[0].isoformat(),
            self._candles.index[-1].isoformat(),
        )

    def load_dataframe(self, df: pd.DataFrame) -> None:
        """Load an externally provided candle DataFrame."""
        self._candles = self._regime.add_indicators(df)
        logger.info("Loaded %d candles from DataFrame", len(self._candles))

    async def init_paper(self) -> None:
        """Initialise CCXT exchange and fetch initial candle history."""
        try:
            import ccxt.async_support as ccxt
        except ImportError:
            raise RuntimeError("ccxt not installed. Run: pip install ccxt")

        cfg = self._config.paper
        exchange_cls = getattr(ccxt, cfg.exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown CCXT exchange: {cfg.exchange_id}")

        params: dict = {}
        if cfg.api_key:
            params["apiKey"] = cfg.api_key
        if cfg.api_secret:
            params["secret"] = cfg.api_secret

        exchange = exchange_cls(params)

        if cfg.require_sandbox:
            if exchange.has.get("sandbox", False):
                exchange.set_sandbox_mode(True)
                logger.info("Exchange sandbox mode enabled.")
            else:
                await exchange.close()
                raise RuntimeError(
                    f"Exchange {cfg.exchange_id} does not support sandbox mode. "
                    "Set require_sandbox=false or choose a sandbox-capable exchange."
                )

        self._exchange = exchange
        await self._fetch_live_candles()

    async def refresh_candles(self) -> None:
        """Fetch latest candles from exchange (paper mode)."""
        if self._exchange is None:
            return
        await self._fetch_live_candles()

    async def close(self) -> None:
        if self._exchange is not None:
            await self._exchange.close()

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    @property
    def candles(self) -> pd.DataFrame:
        return self._candles

    def current_price(self) -> float:
        if self._candles.empty:
            return 0.0
        return float(self._candles["close"].iloc[-1])

    def current_atr(self) -> float:
        if self._candles.empty or "atr" not in self._candles.columns:
            return 0.0
        return float(self._candles["atr"].dropna().iloc[-1])

    def volatility_regime(self) -> VolatilityRegime:
        if self._candles.empty:
            return VolatilityRegime.NORMAL
        return self._regime.detect_volatility_regime(self._candles)

    def regime_summary(self) -> dict:
        if self._candles.empty:
            return {"volatility_regime": "NORMAL", "trend_regime": "SIDEWAYS"}
        return self._regime.get_regime_summary(self._candles)

    def get_window(self, n: int) -> pd.DataFrame:
        """Return last *n* candles."""
        return self._candles.iloc[-n:].copy()

    def append_candle(self, candle: dict) -> None:
        """Append a single candle dict to the buffer."""
        ts = candle.get("timestamp")
        row = pd.DataFrame([candle]).set_index("timestamp")
        self._candles = pd.concat([self._candles, row]).iloc[-self._mc.candle_window:]
        self._candles = self._regime.add_indicators(self._candles)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tf_minutes(self) -> int:
        tf = self._mc.timeframe
        multipliers = {"m": 1, "h": 60, "d": 1440}
        try:
            num = int(tf[:-1])
            unit = tf[-1].lower()
            return num * multipliers.get(unit, 1)
        except (ValueError, IndexError):
            return 5

    async def _fetch_live_candles(self) -> None:
        if self._exchange is None:
            return
        try:
            raw = await self._exchange.fetch_ohlcv(
                self._mc.symbol,
                timeframe=self._mc.timeframe,
                limit=self._mc.candle_window,
            )
            df = pd.DataFrame(
                raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp").sort_index()
            self._candles = self._regime.add_indicators(df)
            logger.info("Fetched %d live candles from exchange", len(self._candles))
        except Exception as exc:
            logger.error("Failed to fetch candles: %s", exc)
