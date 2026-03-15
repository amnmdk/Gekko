"""
Transaction Cost Model (Step 3).

Realistic cost modelling for backtests to eliminate the
"perfect fill" assumption that plagues amateur quant research.

Cost components:
  1. Exchange fees       — maker/taker fee schedule
  2. Bid-ask spread      — half-spread cost on each side
  3. Slippage            — price impact from latency
  4. Partial fills       — reduced fill rate for large orders
  5. Market impact       — permanent price impact from order flow

Total cost = exchange_fee + spread_cost + slippage + market_impact

All costs are expressed in quote currency (e.g., USDT).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FeeSchedule:
    """Exchange fee schedule."""
    maker_fee: float = 0.001    # 0.10% (10 bps)
    taker_fee: float = 0.001    # 0.10%
    rebate: float = 0.0         # Maker rebate (some exchanges)
    min_fee: float = 0.0        # Minimum fee per trade


@dataclass
class CostEstimate:
    """Breakdown of all transaction costs for a single trade."""
    exchange_fee: float = 0.0
    spread_cost: float = 0.0
    slippage: float = 0.0
    market_impact: float = 0.0
    partial_fill_penalty: float = 0.0
    total_cost: float = 0.0
    fill_rate: float = 1.0       # Fraction of order filled [0, 1]
    effective_price: float = 0.0  # Price after all costs

    def to_dict(self) -> dict:
        return {
            "exchange_fee": round(self.exchange_fee, 6),
            "spread_cost": round(self.spread_cost, 6),
            "slippage": round(self.slippage, 6),
            "market_impact": round(self.market_impact, 6),
            "partial_fill_penalty": round(self.partial_fill_penalty, 6),
            "total_cost": round(self.total_cost, 6),
            "fill_rate": round(self.fill_rate, 4),
            "effective_price": round(self.effective_price, 6),
        }


class TransactionCostModel:
    """
    Estimates realistic transaction costs for order execution.

    Parameters
    ----------
    fee_schedule : FeeSchedule
        Exchange fee configuration.
    default_spread_bps : float
        Default bid-ask half-spread in basis points.
    slippage_bps : float
        Expected slippage in basis points per trade.
    market_impact_coefficient : float
        Kyle's lambda: permanent impact = coeff × sqrt(order_size / ADV).
    avg_daily_volume : float
        Average daily volume for market impact estimation.
    """

    def __init__(
        self,
        fee_schedule: Optional[FeeSchedule] = None,
        default_spread_bps: float = 3.0,
        slippage_bps: float = 1.0,
        market_impact_coefficient: float = 0.1,
        avg_daily_volume: float = 1_000_000.0,
    ) -> None:
        self._fees = fee_schedule or FeeSchedule()
        self._spread_bps = default_spread_bps
        self._slippage_bps = slippage_bps
        self._impact_coeff = market_impact_coefficient
        self._adv = avg_daily_volume

    def estimate(
        self,
        price: float,
        size: float,
        direction: str,
        is_maker: bool = False,
        spread_bps: Optional[float] = None,
        volume: Optional[float] = None,
    ) -> CostEstimate:
        """
        Estimate total transaction cost for a trade.

        Parameters
        ----------
        price : float
            Reference price (mid-market).
        size : float
            Order size in base currency units.
        direction : str
            "LONG" (buy) or "SHORT" (sell).
        is_maker : bool
            Whether this is a maker (limit) order.
        spread_bps : float, optional
            Override bid-ask spread in basis points.
        volume : float, optional
            Override average daily volume for impact calc.
        """
        notional = price * size
        spread = spread_bps if spread_bps is not None else self._spread_bps
        adv = volume if volume is not None else self._adv

        # 1. Exchange fees
        fee_rate = self._fees.maker_fee if is_maker else self._fees.taker_fee
        if is_maker and self._fees.rebate > 0:
            fee_rate = max(0, fee_rate - self._fees.rebate)
        exchange_fee = max(self._fees.min_fee, notional * fee_rate)

        # 2. Bid-ask spread cost (half-spread per side)
        spread_cost = notional * (spread / 10000.0)

        # 3. Slippage (market order execution delay)
        slippage = notional * (self._slippage_bps / 10000.0)

        # 4. Market impact (Kyle's lambda model)
        #    Impact = lambda * sqrt(Q / ADV)
        participation_rate = (notional / adv) if adv > 0 else 0
        market_impact = (
            self._impact_coeff
            * math.sqrt(participation_rate)
            * notional
        )

        # 5. Partial fill estimation
        fill_rate = self._estimate_fill_rate(notional, adv)
        partial_penalty = 0.0
        if fill_rate < 1.0:
            # Unfilled portion incurs opportunity cost
            unfilled_fraction = 1.0 - fill_rate
            partial_penalty = unfilled_fraction * notional * 0.001

        # Total cost
        total = (
            exchange_fee + spread_cost + slippage
            + market_impact + partial_penalty
        )

        # Effective price
        if direction == "LONG":
            effective_price = price + total / max(size, 1e-10)
        else:
            effective_price = price - total / max(size, 1e-10)

        return CostEstimate(
            exchange_fee=exchange_fee,
            spread_cost=spread_cost,
            slippage=slippage,
            market_impact=market_impact,
            partial_fill_penalty=partial_penalty,
            total_cost=total,
            fill_rate=fill_rate,
            effective_price=effective_price,
        )

    def estimate_roundtrip(
        self,
        entry_price: float,
        exit_price: float,
        size: float,
        direction: str,
    ) -> dict:
        """
        Estimate roundtrip costs (entry + exit).

        Returns total cost and net PnL after costs.
        """
        entry_cost = self.estimate(entry_price, size, direction)
        exit_dir = "SHORT" if direction == "LONG" else "LONG"
        exit_cost = self.estimate(exit_price, size, exit_dir)

        total_cost = entry_cost.total_cost + exit_cost.total_cost

        if direction == "LONG":
            gross_pnl = (exit_price - entry_price) * size
        else:
            gross_pnl = (entry_price - exit_price) * size

        net_pnl = gross_pnl - total_cost

        return {
            "gross_pnl": round(gross_pnl, 6),
            "total_cost": round(total_cost, 6),
            "net_pnl": round(net_pnl, 6),
            "cost_pct": round(
                total_cost / max(abs(gross_pnl), 1e-10) * 100, 2
            ),
            "entry_cost": entry_cost.to_dict(),
            "exit_cost": exit_cost.to_dict(),
        }

    def _estimate_fill_rate(
        self, notional: float, adv: float,
    ) -> float:
        """
        Estimate fill probability based on order size vs liquidity.
        Uses exponential decay model.
        """
        if adv <= 0:
            return 0.5
        participation = notional / adv
        # Fill rate decays as participation increases
        # 1% participation → ~99% fill, 10% → ~90%, 50% → ~60%
        fill_rate = math.exp(-participation * 5)
        return max(0.1, min(1.0, fill_rate))

    @property
    def config(self) -> dict:
        return {
            "maker_fee": self._fees.maker_fee,
            "taker_fee": self._fees.taker_fee,
            "spread_bps": self._spread_bps,
            "slippage_bps": self._slippage_bps,
            "impact_coefficient": self._impact_coeff,
            "avg_daily_volume": self._adv,
        }
