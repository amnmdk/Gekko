"""
Strategy Market Impact Model (Step 10).

Estimates the real-world costs of executing a strategy:

  Components:
    1. Temporary impact — price displacement during execution
    2. Permanent impact — information leakage to market
    3. Slippage — execution price vs decision price
    4. Liquidity constraints — maximum executable size
    5. Timing costs — delay between signal and execution

  Models:
    - Square-root impact (Almgren-Chriss)
    - Linear impact (Kyle)
    - Power-law impact (Bouchaud)

  Output: Impact estimates for position sizing and cost budgeting.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ImpactEstimate:
    """Complete market impact estimate for a trade."""

    symbol: str
    side: str                       # "buy" or "sell"
    quantity: float
    price: float
    temporary_impact_bps: float = 0.0
    permanent_impact_bps: float = 0.0
    spread_cost_bps: float = 0.0
    timing_cost_bps: float = 0.0
    total_impact_bps: float = 0.0
    total_cost_usd: float = 0.0
    execution_pct_adv: float = 0.0   # As % of average daily volume
    max_executable_qty: float = 0.0
    model_used: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": round(self.quantity, 6),
            "price": round(self.price, 4),
            "temporary_impact_bps": round(self.temporary_impact_bps, 2),
            "permanent_impact_bps": round(self.permanent_impact_bps, 2),
            "spread_cost_bps": round(self.spread_cost_bps, 2),
            "timing_cost_bps": round(self.timing_cost_bps, 2),
            "total_impact_bps": round(self.total_impact_bps, 2),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "execution_pct_adv": round(self.execution_pct_adv, 4),
            "max_executable_qty": round(self.max_executable_qty, 4),
            "model_used": self.model_used,
            "details": self.details,
        }


@dataclass
class MarketParams:
    """Market parameters for impact estimation."""

    symbol: str = "BTC/USDT"
    daily_volume: float = 1_000_000.0    # Average daily volume (units)
    daily_volatility: float = 0.02       # Daily return volatility
    spread_bps: float = 5.0              # Typical bid-ask spread
    tick_size: float = 0.01              # Minimum price increment
    avg_trade_size: float = 100.0        # Average trade size (units)


class MarketImpactModel:
    """
    Estimates market impact for strategy execution.

    Usage:
        model = MarketImpactModel()
        params = MarketParams(
            symbol="BTC/USDT",
            daily_volume=50_000,
            daily_volatility=0.025,
            spread_bps=8.0,
        )
        estimate = model.estimate(
            params=params,
            quantity=10.0,
            price=50000.0,
            side="buy",
        )
    """

    def __init__(
        self,
        model_type: str = "almgren_chriss",
        participation_limit: float = 0.10,  # Max 10% of ADV
        urgency_factor: float = 0.5,        # [0=patient, 1=urgent]
    ) -> None:
        self._model_type = model_type
        self._participation_limit = participation_limit
        self._urgency = urgency_factor

    def estimate(
        self,
        params: MarketParams,
        quantity: float,
        price: float,
        side: str = "buy",
        model: str | None = None,
    ) -> ImpactEstimate:
        """
        Estimate total market impact.

        Parameters
        ----------
        params : market parameters
        quantity : order size in base units
        price : current market price
        side : "buy" or "sell"
        model : override model type
        """
        model_type = model or self._model_type
        adv = params.daily_volume
        pct_adv = quantity / max(adv, 1e-10)

        # Maximum executable quantity
        max_qty = adv * self._participation_limit

        # 1. Spread cost (always paid)
        spread_bps = params.spread_bps / 2  # Half spread

        # 2. Temporary impact
        if model_type == "almgren_chriss":
            temp_bps, perm_bps = self._almgren_chriss(
                pct_adv, params.daily_volatility,
            )
        elif model_type == "kyle":
            temp_bps, perm_bps = self._kyle_model(
                pct_adv, params.daily_volatility,
            )
        elif model_type == "power_law":
            temp_bps, perm_bps = self._power_law(
                pct_adv, params.daily_volatility,
            )
        else:
            temp_bps, perm_bps = self._almgren_chriss(
                pct_adv, params.daily_volatility,
            )

        # 3. Timing cost (waiting cost due to signal decay)
        timing_bps = self._timing_cost(params.daily_volatility)

        # Total
        total_bps = spread_bps + temp_bps + perm_bps + timing_bps
        notional = quantity * price
        total_usd = notional * total_bps / 10000

        est = ImpactEstimate(
            symbol=params.symbol,
            side=side,
            quantity=quantity,
            price=price,
            temporary_impact_bps=temp_bps,
            permanent_impact_bps=perm_bps,
            spread_cost_bps=spread_bps,
            timing_cost_bps=timing_bps,
            total_impact_bps=total_bps,
            total_cost_usd=total_usd,
            execution_pct_adv=pct_adv * 100,
            max_executable_qty=max_qty,
            model_used=model_type,
            details={
                "adv": adv,
                "notional": round(notional, 2),
                "urgency": self._urgency,
                "participation_limit": self._participation_limit,
            },
        )

        logger.info(
            "Impact estimate [%s %s %.4f @ %.2f]: total=%.1f bps ($%.2f)",
            side, params.symbol, quantity, price, total_bps, total_usd,
        )
        return est

    def _almgren_chriss(
        self, pct_adv: float, volatility: float,
    ) -> tuple[float, float]:
        """
        Almgren-Chriss square-root impact model.

        Temporary impact: sigma * sqrt(pct_adv / urgency)
        Permanent impact: sigma * pct_adv * gamma
        """
        sigma_bps = volatility * 10000

        # Temporary: square-root law
        temp_bps = sigma_bps * math.sqrt(
            abs(pct_adv) / max(self._urgency, 0.1)
        ) * 0.1

        # Permanent: linear in participation
        gamma = 0.3  # Permanent impact coefficient
        perm_bps = sigma_bps * abs(pct_adv) * gamma

        return temp_bps, perm_bps

    def _kyle_model(
        self, pct_adv: float, volatility: float,
    ) -> tuple[float, float]:
        """
        Kyle's linear impact model.

        Impact = lambda * Q where lambda = sigma / sqrt(ADV)
        """
        sigma_bps = volatility * 10000
        kyle_lambda = sigma_bps * 0.05

        temp_bps = kyle_lambda * abs(pct_adv) * 10000
        perm_bps = temp_bps * 0.3  # 30% permanent

        return temp_bps, perm_bps

    def _power_law(
        self, pct_adv: float, volatility: float,
    ) -> tuple[float, float]:
        """
        Bouchaud power-law impact model.

        Impact ~ sigma * (Q/V)^0.5 (concave)
        """
        sigma_bps = volatility * 10000
        exponent = 0.5

        temp_bps = sigma_bps * (abs(pct_adv) ** exponent) * 0.2
        perm_bps = temp_bps * 0.25

        return temp_bps, perm_bps

    def _timing_cost(self, volatility: float) -> float:
        """
        Timing cost: opportunity cost of waiting.

        For patient execution, the signal may decay.
        Cost = vol * sqrt(execution_time) * alpha_decay_rate
        """
        execution_hours = 1.0 / max(self._urgency, 0.1)
        alpha_decay = 0.1  # 10% signal decay per hour (assumed)
        timing = volatility * 10000 * math.sqrt(
            execution_hours / 24,
        ) * alpha_decay
        return timing

    def optimal_execution_schedule(
        self,
        params: MarketParams,
        total_quantity: float,
        n_slices: int = 10,
    ) -> list[dict]:
        """
        Compute optimal execution schedule (TWAP-like with impact awareness).

        Returns list of (slice_quantity, expected_impact) pairs.
        """
        schedule = []
        remaining = total_quantity
        adv = params.daily_volume

        for i in range(n_slices):
            # TWAP base slice
            base_slice = total_quantity / n_slices

            # Adjust: front-load if urgent, back-load if patient
            urgency_adj = 1.0 + (self._urgency - 0.5) * (
                1.0 - 2.0 * i / max(n_slices - 1, 1)
            )
            slice_qty = min(base_slice * urgency_adj, remaining)
            slice_qty = max(slice_qty, 0)

            pct_adv = slice_qty / max(adv, 1e-10)
            temp, perm = self._almgren_chriss(pct_adv, params.daily_volatility)

            schedule.append({
                "slice": i + 1,
                "quantity": round(slice_qty, 6),
                "pct_adv": round(pct_adv * 100, 4),
                "expected_impact_bps": round(temp + perm, 2),
            })
            remaining -= slice_qty

        return schedule
