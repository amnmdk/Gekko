"""
Market Microstructure Features (Step 4).

Extracts features from order book dynamics and trade flow data
for combining with news event signals:

  Features:
    1. Order book imbalance — bid vs ask depth ratio
    2. Trade flow imbalance — buy vs sell volume ratio
    3. Volatility bursts — sudden realised vol spikes
    4. Liquidity shocks — spread widening events
    5. Price impact — return per unit volume
    6. VWAP deviation — distance from volume-weighted average price
    7. Tick direction — uptick/downtick ratio
    8. Kyle's lambda — price impact coefficient

  All features designed for real-time streaming or batch computation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MicrostructureSnapshot:
    """A single microstructure feature snapshot."""

    timestamp: str = ""
    order_book_imbalance: float = 0.0
    trade_flow_imbalance: float = 0.0
    volatility_burst: float = 0.0
    liquidity_shock: float = 0.0
    price_impact: float = 0.0
    vwap_deviation: float = 0.0
    tick_direction: float = 0.0
    kyle_lambda: float = 0.0
    spread_bps: float = 0.0
    depth_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "order_book_imbalance": round(self.order_book_imbalance, 6),
            "trade_flow_imbalance": round(self.trade_flow_imbalance, 6),
            "volatility_burst": round(self.volatility_burst, 6),
            "liquidity_shock": round(self.liquidity_shock, 6),
            "price_impact": round(self.price_impact, 6),
            "vwap_deviation": round(self.vwap_deviation, 6),
            "tick_direction": round(self.tick_direction, 6),
            "kyle_lambda": round(self.kyle_lambda, 6),
            "spread_bps": round(self.spread_bps, 4),
            "depth_ratio": round(self.depth_ratio, 4),
        }

    def to_vector(self) -> np.ndarray:
        """Convert to feature vector."""
        return np.array([
            self.order_book_imbalance,
            self.trade_flow_imbalance,
            self.volatility_burst,
            self.liquidity_shock,
            self.price_impact,
            self.vwap_deviation,
            self.tick_direction,
            self.kyle_lambda,
            self.spread_bps,
            self.depth_ratio,
        ])


class MarketMicrostructureEngine:
    """
    Extracts microstructure features from trade and order book data.

    Usage:
        engine = MarketMicrostructureEngine()
        engine.update_trade(price=100.5, volume=10, side="buy")
        engine.update_orderbook(bids=[(100, 50)], asks=[(101, 30)])
        features = engine.compute_features()
    """

    def __init__(
        self,
        vol_window: int = 50,
        flow_window: int = 100,
        spread_baseline_bps: float = 10.0,
    ) -> None:
        self._vol_window = vol_window
        self._flow_window = flow_window
        self._spread_baseline = spread_baseline_bps

        # Trade accumulators
        self._prices: list[float] = []
        self._volumes: list[float] = []
        self._sides: list[str] = []
        self._buy_volume: list[float] = []
        self._sell_volume: list[float] = []

        # Order book state
        self._best_bid: float = 0.0
        self._best_ask: float = 0.0
        self._bid_depth: float = 0.0
        self._ask_depth: float = 0.0

        # VWAP accumulator
        self._vwap_pv_sum: float = 0.0
        self._vwap_v_sum: float = 0.0

    def update_trade(
        self,
        price: float,
        volume: float,
        side: str = "unknown",
    ) -> None:
        """Record a trade tick."""
        self._prices.append(price)
        self._volumes.append(volume)
        self._sides.append(side)

        if side == "buy":
            self._buy_volume.append(volume)
            self._sell_volume.append(0.0)
        elif side == "sell":
            self._buy_volume.append(0.0)
            self._sell_volume.append(volume)
        else:
            self._buy_volume.append(volume / 2)
            self._sell_volume.append(volume / 2)

        self._vwap_pv_sum += price * volume
        self._vwap_v_sum += volume

    def update_orderbook(
        self,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
    ) -> None:
        """
        Update order book state.

        Parameters
        ----------
        bids : list of (price, quantity)
        asks : list of (price, quantity)
        """
        if bids:
            self._best_bid = bids[0][0]
            self._bid_depth = sum(q for _, q in bids)
        if asks:
            self._best_ask = asks[0][0]
            self._ask_depth = sum(q for _, q in asks)

    def compute_features(self, timestamp: str = "") -> MicrostructureSnapshot:
        """Compute all microstructure features from accumulated data."""
        snap = MicrostructureSnapshot(timestamp=timestamp)

        # 1. Order book imbalance: (bid_depth - ask_depth) / total
        total_depth = self._bid_depth + self._ask_depth
        if total_depth > 0:
            snap.order_book_imbalance = (
                (self._bid_depth - self._ask_depth) / total_depth
            )
            snap.depth_ratio = self._bid_depth / max(self._ask_depth, 1e-10)

        # 2. Trade flow imbalance
        window = self._flow_window
        recent_buy = self._buy_volume[-window:]
        recent_sell = self._sell_volume[-window:]
        total_flow = sum(recent_buy) + sum(recent_sell)
        if total_flow > 0:
            snap.trade_flow_imbalance = (
                (sum(recent_buy) - sum(recent_sell)) / total_flow
            )

        # 3. Volatility burst
        if len(self._prices) >= self._vol_window:
            recent_prices = np.array(self._prices[-self._vol_window:])
            returns = np.diff(np.log(np.maximum(recent_prices, 1e-10)))
            if len(returns) >= 2:
                recent_vol = float(np.std(returns, ddof=1))
                # Compare recent vol to longer-term
                if len(self._prices) >= self._vol_window * 2:
                    longer = np.array(
                        self._prices[-self._vol_window * 2:-self._vol_window]
                    )
                    longer_ret = np.diff(
                        np.log(np.maximum(longer, 1e-10))
                    )
                    baseline_vol = float(np.std(longer_ret, ddof=1))
                    if baseline_vol > 0:
                        snap.volatility_burst = recent_vol / baseline_vol
                    else:
                        snap.volatility_burst = 1.0
                else:
                    snap.volatility_burst = 1.0

        # 4. Liquidity shock (spread widening)
        mid = (self._best_bid + self._best_ask) / 2 if self._best_ask > 0 else 0
        if mid > 0:
            spread_bps = (self._best_ask - self._best_bid) / mid * 10000
            snap.spread_bps = spread_bps
            snap.liquidity_shock = max(
                0.0, (spread_bps - self._spread_baseline) / self._spread_baseline,
            )

        # 5. Price impact: return per unit volume
        if len(self._prices) >= 2 and len(self._volumes) >= 2:
            ret = (self._prices[-1] - self._prices[-2]) / max(
                self._prices[-2], 1e-10,
            )
            vol = self._volumes[-1]
            snap.price_impact = ret / max(vol, 1e-10)

        # 6. VWAP deviation
        if self._vwap_v_sum > 0 and self._prices:
            vwap = self._vwap_pv_sum / self._vwap_v_sum
            current_price = self._prices[-1]
            snap.vwap_deviation = (current_price - vwap) / max(vwap, 1e-10)

        # 7. Tick direction (uptick/downtick ratio)
        if len(self._prices) >= 10:
            recent = self._prices[-10:]
            upticks = sum(
                1 for j in range(1, len(recent)) if recent[j] > recent[j - 1]
            )
            downticks = sum(
                1 for j in range(1, len(recent)) if recent[j] < recent[j - 1]
            )
            total_ticks = upticks + downticks
            if total_ticks > 0:
                snap.tick_direction = (upticks - downticks) / total_ticks

        # 8. Kyle's lambda estimate
        snap.kyle_lambda = self._estimate_kyle_lambda()

        return snap

    def _estimate_kyle_lambda(self) -> float:
        """
        Estimate Kyle's lambda (price impact coefficient).

        lambda = Cov(delta_P, signed_volume) / Var(signed_volume)
        """
        n = min(len(self._prices), len(self._volumes), 50)
        if n < 10:
            return 0.0

        prices = np.array(self._prices[-n:])
        buy_v = np.array(self._buy_volume[-n:])
        sell_v = np.array(self._sell_volume[-n:])

        delta_p = np.diff(prices)
        signed_vol = (buy_v[1:] - sell_v[1:])

        if len(delta_p) < 5:
            return 0.0

        var_sv = float(np.var(signed_vol, ddof=1))
        if var_sv <= 0:
            return 0.0

        cov = float(np.cov(delta_p, signed_vol)[0, 1])
        return cov / var_sv

    def compute_batch(
        self,
        prices: np.ndarray,
        volumes: np.ndarray,
        spreads_bps: np.ndarray | None = None,
    ) -> list[MicrostructureSnapshot]:
        """
        Compute features over a batch of OHLCV-like data.

        Parameters
        ----------
        prices : array of close prices
        volumes : array of volumes
        spreads_bps : array of bid-ask spreads in basis points
        """
        n = len(prices)
        snapshots: list[MicrostructureSnapshot] = []

        for i in range(n):
            self.update_trade(
                price=float(prices[i]),
                volume=float(volumes[i]),
                side="buy" if i > 0 and prices[i] > prices[i - 1] else "sell",
            )

            if spreads_bps is not None:
                mid = float(prices[i])
                spread = float(spreads_bps[i]) * mid / 10000
                self.update_orderbook(
                    bids=[(mid - spread / 2, float(volumes[i]))],
                    asks=[(mid + spread / 2, float(volumes[i]))],
                )

            snap = self.compute_features(timestamp=f"t_{i}")
            snapshots.append(snap)

        logger.info("Computed %d microstructure snapshots", len(snapshots))
        return snapshots

    def feature_names(self) -> list[str]:
        """Return ordered feature names."""
        return [
            "order_book_imbalance",
            "trade_flow_imbalance",
            "volatility_burst",
            "liquidity_shock",
            "price_impact",
            "vwap_deviation",
            "tick_direction",
            "kyle_lambda",
            "spread_bps",
            "depth_ratio",
        ]

    def reset(self) -> None:
        """Reset all accumulators."""
        self._prices.clear()
        self._volumes.clear()
        self._sides.clear()
        self._buy_volume.clear()
        self._sell_volume.clear()
        self._best_bid = 0.0
        self._best_ask = 0.0
        self._bid_depth = 0.0
        self._ask_depth = 0.0
        self._vwap_pv_sum = 0.0
        self._vwap_v_sum = 0.0
