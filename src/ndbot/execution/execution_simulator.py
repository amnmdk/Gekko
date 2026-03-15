"""
Execution Simulation Engine (Step 4).

Simulates realistic order execution including:
  - Network latency modelling
  - Order book depth simulation
  - Partial fills based on liquidity
  - Cancel/retry logic for unfilled orders
  - Order lifecycle tracking (pending → partial → filled / cancelled)

This replaces the naive "instant fill at mid price" assumption
with realistic execution dynamics.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from .cost_model import CostEstimate, TransactionCostModel

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class SimulatedOrder:
    """An order progressing through the execution simulator."""
    order_id: str
    symbol: str
    direction: str        # "LONG" or "SHORT"
    order_type: OrderType
    requested_size: float
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    cost_estimate: Optional[CostEstimate] = None
    created_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    cancel_reason: str = ""
    attempts: int = 0
    max_attempts: int = 3
    fills: list[dict] = field(default_factory=list)

    @property
    def fill_rate(self) -> float:
        if self.requested_size <= 0:
            return 0.0
        return self.filled_size / self.requested_size

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED, OrderStatus.CANCELLED,
            OrderStatus.REJECTED, OrderStatus.EXPIRED,
        )

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "order_type": self.order_type.value,
            "requested_size": self.requested_size,
            "limit_price": self.limit_price,
            "status": self.status.value,
            "filled_size": round(self.filled_size, 6),
            "avg_fill_price": round(self.avg_fill_price, 6),
            "fill_rate": round(self.fill_rate, 4),
            "attempts": self.attempts,
            "fills": self.fills,
        }


@dataclass
class LatencyConfig:
    """Network and exchange latency parameters."""
    network_latency_ms: float = 50.0       # One-way network delay
    exchange_latency_ms: float = 10.0      # Exchange matching engine
    latency_jitter_ms: float = 20.0        # Random jitter
    order_timeout_seconds: float = 30.0    # Cancel unfilled after this


class ExecutionSimulator:
    """
    Simulates realistic order execution.

    Instead of instant fills at mid price, orders pass through:
      1. Latency delay
      2. Price check against order book depth
      3. Partial fill based on available liquidity
      4. Cost computation
      5. Retry logic if partially filled
    """

    def __init__(
        self,
        cost_model: Optional[TransactionCostModel] = None,
        latency: Optional[LatencyConfig] = None,
        seed: int = 42,
    ) -> None:
        self._cost_model = cost_model or TransactionCostModel()
        self._latency = latency or LatencyConfig()
        self._rng = random.Random(seed)
        self._orders: dict[str, SimulatedOrder] = {}
        self._order_counter = 0
        self._stats = {
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_partial": 0,
            "orders_cancelled": 0,
            "orders_rejected": 0,
            "total_slippage": 0.0,
        }

    def submit_order(
        self,
        symbol: str,
        direction: str,
        size: float,
        current_price: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        current_time: Optional[datetime] = None,
    ) -> SimulatedOrder:
        """
        Submit an order to the execution simulator.

        Returns the SimulatedOrder with initial status.
        The order must then be processed via process_order().
        """
        self._order_counter += 1
        order_id = f"SIM_{self._order_counter:06d}"

        order = SimulatedOrder(
            order_id=order_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            requested_size=size,
            limit_price=limit_price or current_price,
            created_at=current_time or datetime.now(timezone.utc),
        )
        self._orders[order_id] = order
        self._stats["orders_submitted"] += 1

        logger.debug(
            "Order submitted: %s %s %s %.6f @ %.4f",
            order_id, direction, symbol, size, current_price,
        )
        return order

    def process_order(
        self,
        order: SimulatedOrder,
        current_price: float,
        available_volume: float = 1_000_000.0,
        current_time: Optional[datetime] = None,
    ) -> SimulatedOrder:
        """
        Process an order through the execution pipeline.

        Steps:
          1. Apply latency
          2. Check price (limit orders)
          3. Determine fill amount based on liquidity
          4. Compute costs
          5. Update order state
        """
        if order.is_terminal:
            return order

        now = current_time or datetime.now(timezone.utc)
        order.attempts += 1

        # 1. Simulate latency
        latency_ms = (
            self._latency.network_latency_ms
            + self._latency.exchange_latency_ms
            + self._rng.gauss(0, self._latency.latency_jitter_ms)
        )
        latency_ms = max(1.0, latency_ms)
        execution_time = now + timedelta(milliseconds=latency_ms)

        # Price moved during latency — simulate price impact
        price_drift = self._rng.gauss(0, 0.0001) * current_price
        execution_price = current_price + price_drift

        # 2. Limit order check
        if order.order_type == OrderType.LIMIT:
            if order.direction == "LONG" and execution_price > order.limit_price:
                if order.attempts >= order.max_attempts:
                    order.status = OrderStatus.EXPIRED
                    order.cancel_reason = "limit_price_not_reached"
                    self._stats["orders_cancelled"] += 1
                return order
            if order.direction == "SHORT" and execution_price < order.limit_price:
                if order.attempts >= order.max_attempts:
                    order.status = OrderStatus.EXPIRED
                    order.cancel_reason = "limit_price_not_reached"
                    self._stats["orders_cancelled"] += 1
                return order

        # 3. Determine fill amount
        remaining = order.requested_size - order.filled_size
        liquidity_fill_rate = min(
            1.0, available_volume / max(remaining * execution_price, 1),
        )
        # Random fill variation
        fill_rate = min(1.0, liquidity_fill_rate * (
            0.8 + self._rng.random() * 0.2
        ))
        fill_size = remaining * fill_rate

        if fill_size < remaining * 0.01:
            # Too small to bother
            if order.attempts >= order.max_attempts:
                if order.filled_size > 0:
                    order.status = OrderStatus.PARTIAL
                    self._stats["orders_partial"] += 1
                else:
                    order.status = OrderStatus.CANCELLED
                    order.cancel_reason = "no_liquidity"
                    self._stats["orders_cancelled"] += 1
            return order

        # 4. Compute costs
        cost = self._cost_model.estimate(
            execution_price, fill_size, order.direction,
            is_maker=(order.order_type == OrderType.LIMIT),
        )

        # 5. Update order state
        fill_record = {
            "fill_size": round(fill_size, 6),
            "fill_price": round(cost.effective_price, 6),
            "timestamp": execution_time.isoformat(),
            "latency_ms": round(latency_ms, 1),
            "cost": cost.to_dict(),
        }
        order.fills.append(fill_record)

        # Weighted average fill price
        prev_notional = order.avg_fill_price * order.filled_size
        new_notional = cost.effective_price * fill_size
        order.filled_size += fill_size
        order.avg_fill_price = (
            (prev_notional + new_notional) / order.filled_size
        )
        order.cost_estimate = cost
        order.filled_at = execution_time

        # Track slippage
        slippage = abs(cost.effective_price - current_price) * fill_size
        self._stats["total_slippage"] += slippage

        # Check if fully filled
        if order.filled_size >= order.requested_size * 0.99:
            order.status = OrderStatus.FILLED
            self._stats["orders_filled"] += 1
        else:
            order.status = OrderStatus.PARTIAL

        logger.debug(
            "Fill: %s %.6f/%.6f @ %.4f (latency=%dms)",
            order.order_id, order.filled_size, order.requested_size,
            cost.effective_price, int(latency_ms),
        )
        return order

    def cancel_order(self, order_id: str, reason: str = "user") -> bool:
        """Cancel a pending or partial order."""
        order = self._orders.get(order_id)
        if not order or order.is_terminal:
            return False
        order.status = OrderStatus.CANCELLED
        order.cancel_reason = reason
        self._stats["orders_cancelled"] += 1
        return True

    def get_order(self, order_id: str) -> Optional[SimulatedOrder]:
        return self._orders.get(order_id)

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    @property
    def pending_orders(self) -> list[SimulatedOrder]:
        return [
            o for o in self._orders.values()
            if not o.is_terminal
        ]
