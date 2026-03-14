"""
Market regime detection.

Classifies market into volatility regimes:
  LOW    — subdued volatility, trend-following more reliable
  NORMAL — average conditions
  HIGH   — elevated volatility, reduce position sizing

Detection methods:
  1. Volatility regime: rolling ATR percentile vs historical window
  2. Trend regime: slope of long-period MA (positive = uptrend, negative = downtrend)

Signals must query regime before entering trades.
"""
from __future__ import annotations

import logging
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class TrendRegime(str, Enum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    SIDEWAYS = "SIDEWAYS"


class RegimeDetector:
    """
    Detects volatility and trend regime from OHLCV candle data.

    Parameters
    ----------
    atr_period: int
        Period for ATR calculation.
    atr_percentile_window: int
        Number of candles to use for ATR percentile ranking.
    low_percentile: float
        ATR percentile below which regime is LOW.
    high_percentile: float
        ATR percentile above which regime is HIGH.
    ma_short: int
        Short MA period for trend detection.
    ma_long: int
        Long MA period for trend detection.
    slope_threshold: float
        Minimum absolute slope (normalised) to classify as trending.
    """

    def __init__(
        self,
        atr_period: int = 14,
        atr_percentile_window: int = 100,
        low_percentile: float = 25.0,
        high_percentile: float = 75.0,
        ma_short: int = 20,
        ma_long: int = 50,
        slope_threshold: float = 0.0002,
    ):
        self._atr_period = atr_period
        self._atr_pct_window = atr_percentile_window
        self._low_pct = low_percentile
        self._high_pct = high_percentile
        self._ma_short = ma_short
        self._ma_long = ma_long
        self._slope_threshold = slope_threshold

    def compute_atr(self, candles: pd.DataFrame) -> pd.Series:
        """
        Compute ATR using Wilder's smoothing method.
        Requires columns: high, low, close.
        """
        high = candles["high"]
        low = candles["low"]
        close = candles["close"]
        prev_close = close.shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1.0 / self._atr_period, adjust=False).mean()
        return atr

    def add_indicators(self, candles: pd.DataFrame) -> pd.DataFrame:
        """
        Add ATR, MA_short, MA_long columns to candles DataFrame.
        Returns the enriched DataFrame.
        """
        df = candles.copy()
        df["atr"] = self.compute_atr(df)
        df["ma_short"] = df["close"].rolling(self._ma_short).mean()
        df["ma_long"] = df["close"].rolling(self._ma_long).mean()
        return df

    def detect_volatility_regime(self, candles: pd.DataFrame) -> VolatilityRegime:
        """
        Classify current volatility regime using ATR percentile.
        Requires 'atr' column; if absent, computes it.
        """
        df = candles if "atr" in candles.columns else self.add_indicators(candles)
        if len(df) < self._atr_pct_window:
            logger.debug("Insufficient candles for regime detection — defaulting NORMAL")
            return VolatilityRegime.NORMAL

        window = df["atr"].dropna().iloc[-self._atr_pct_window:]
        current_atr = float(df["atr"].dropna().iloc[-1])
        percentile = float(
            (window < current_atr).mean() * 100
        )

        if percentile < self._low_pct:
            return VolatilityRegime.LOW
        elif percentile > self._high_pct:
            return VolatilityRegime.HIGH
        return VolatilityRegime.NORMAL

    def detect_trend_regime(self, candles: pd.DataFrame) -> TrendRegime:
        """
        Classify trend regime using MA slope.
        Requires 'ma_long' column; if absent, computes it.
        """
        df = candles if "ma_long" in candles.columns else self.add_indicators(candles)
        ma = df["ma_long"].dropna()
        if len(ma) < 5:
            return TrendRegime.SIDEWAYS

        # Linear regression slope over last 20 MA values
        window = ma.iloc[-20:].values
        x = np.arange(len(window))
        if len(x) < 2:
            return TrendRegime.SIDEWAYS

        slope, _ = np.polyfit(x, window, 1)
        # Normalise by mean price to get relative slope
        mean_price = float(np.mean(window))
        if mean_price == 0:
            return TrendRegime.SIDEWAYS
        norm_slope = slope / mean_price

        if norm_slope > self._slope_threshold:
            return TrendRegime.UPTREND
        elif norm_slope < -self._slope_threshold:
            return TrendRegime.DOWNTREND
        return TrendRegime.SIDEWAYS

    def get_regime_summary(self, candles: pd.DataFrame) -> dict:
        """Return dict with full regime state."""
        df = self.add_indicators(candles)
        vol = self.detect_volatility_regime(df)
        trend = self.detect_trend_regime(df)
        atr_val = float(df["atr"].dropna().iloc[-1]) if "atr" in df.columns and len(df) > 0 else 0.0
        close = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
        return {
            "volatility_regime": vol.value,
            "trend_regime": trend.value,
            "current_atr": round(atr_val, 4),
            "atr_pct_of_price": round(atr_val / close * 100, 4) if close > 0 else 0.0,
        }

    def position_size_multiplier(self, regime: VolatilityRegime) -> float:
        """
        Return a position sizing multiplier based on regime.
        HIGH volatility → reduce size.
        LOW volatility → can increase slightly.
        """
        return {
            VolatilityRegime.LOW: 1.25,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.HIGH: 0.6,
        }[regime]
