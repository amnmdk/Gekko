"""
Synthetic OHLCV candle generator for simulate and backtest modes.

Generates realistic-looking price action using:
  - Geometric Brownian Motion (GBM) base drift
  - Mean-reverting volatility clustering (GARCH-like)
  - Occasional news shock jumps for event study alignment

Output: pd.DataFrame with columns [open, high, low, close, volume, atr]
        indexed by UTC datetime.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd


class SyntheticCandleGenerator:
    """
    Generates synthetic OHLCV candle data.

    Parameters
    ----------
    symbol: str
        Symbol label (cosmetic only).
    start_price: float
        Initial close price.
    daily_vol: float
        Annualised volatility (e.g. 0.6 for 60%).
    daily_drift: float
        Annualised drift (e.g. 0.05 for +5% per year).
    timeframe_minutes: int
        Candle duration in minutes.
    seed: int | None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        start_price: float = 45_000.0,
        daily_vol: float = 0.60,
        daily_drift: float = 0.05,
        timeframe_minutes: int = 5,
        seed: Optional[int] = None,
    ):
        self.symbol = symbol
        self._start_price = start_price
        self._daily_vol = daily_vol
        self._daily_drift = daily_drift
        self._tf_min = timeframe_minutes
        self._rng = np.random.default_rng(seed)
        self._py_rng = random.Random(seed)

        # Convert to per-candle parameters
        minutes_per_year = 365 * 24 * 60
        self._dt = timeframe_minutes / minutes_per_year
        self._drift = daily_drift * (timeframe_minutes / (365 * 24 * 60)) * minutes_per_year / 365
        self._sigma = daily_vol * np.sqrt(self._dt)

    def generate(
        self,
        n_candles: int,
        start_time: Optional[datetime] = None,
        shock_times: Optional[list[datetime]] = None,
        shock_magnitude: float = 0.03,
    ) -> pd.DataFrame:
        """
        Generate *n_candles* OHLCV candles.

        Parameters
        ----------
        start_time: datetime
            Starting timestamp (UTC). Defaults to now - n_candles * timeframe.
        shock_times: list[datetime]
            Optional list of datetimes at which to inject a price shock
            (simulates news event market impact).
        shock_magnitude: float
            Mean absolute shock size as fraction of price.
        """
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(
                minutes=self._tf_min * n_candles
            )

        shock_set = set()
        if shock_times:
            for st in shock_times:
                # Find nearest candle index
                delta = (st - start_time).total_seconds() / 60
                idx = int(delta / self._tf_min)
                if 0 <= idx < n_candles:
                    shock_set.add(idx)

        # GARCH-like volatility state
        vol_state = self._sigma

        closes = np.empty(n_candles)
        opens = np.empty(n_candles)
        highs = np.empty(n_candles)
        lows = np.empty(n_candles)
        volumes = np.empty(n_candles)

        price = self._start_price
        for i in range(n_candles):
            # Volatility clustering: GARCH(1,1)-lite
            noise = self._rng.standard_normal()
            shock_boost = 0.0
            if i in shock_set:
                shock_dir = 1 if self._py_rng.random() > 0.3 else -1
                shock_boost = shock_dir * shock_magnitude * (
                    1 + self._py_rng.uniform(0, 0.5)
                )
                vol_state = min(self._sigma * 4, vol_state * 2.0)

            ret = self._drift * self._dt + vol_state * noise + shock_boost
            opens[i] = price

            close_price = price * np.exp(ret)
            closes[i] = close_price

            # Intra-candle range
            intra_vol = vol_state * self._rng.uniform(0.5, 1.5)
            high_excess = abs(self._rng.normal(0, intra_vol)) * price
            low_excess = abs(self._rng.normal(0, intra_vol)) * price

            if close_price >= price:
                highs[i] = max(price, close_price) + high_excess
                lows[i] = min(price, close_price) - low_excess * 0.5
            else:
                highs[i] = max(price, close_price) + high_excess * 0.5
                lows[i] = min(price, close_price) - low_excess

            highs[i] = max(highs[i], opens[i], closes[i])
            lows[i] = min(lows[i], opens[i], closes[i])
            lows[i] = max(0.01, lows[i])

            # Volume: higher on volatile candles
            base_vol = 1000 + 500 * abs(shock_boost / max(self._sigma, 1e-9))
            volumes[i] = base_vol * self._rng.lognormal(0, 0.5)

            price = close_price
            # Mean-revert volatility
            vol_state = 0.85 * vol_state + 0.15 * self._sigma

        timestamps = [
            start_time + timedelta(minutes=self._tf_min * i)
            for i in range(n_candles)
        ]

        df = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            },
            index=pd.DatetimeIndex(timestamps, tz="UTC"),
        )
        df.index.name = "timestamp"
        return df
