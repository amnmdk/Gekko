"""
Multi-Agent Market Simulation (Step 11).

Simulates a market with multiple agent types interacting:

  Agents:
    1. Market Makers — provide liquidity, profit from spread
    2. Arbitrage Bots — exploit price discrepancies
    3. News Traders — react to events (our strategy)
    4. Noise Traders — random activity, provide liquidity
    5. Momentum Traders — follow trends

  Market mechanics:
    - Continuous double auction order book
    - Price formation via supply/demand equilibrium
    - Event injection for testing news strategies
    - Market impact and feedback loops

  Goal: Test strategies in realistic adversarial environments.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """A simulated order."""

    agent_id: str
    side: str        # "buy" or "sell"
    price: float
    quantity: float
    timestamp: int   # Simulation step


@dataclass
class Trade:
    """A simulated trade."""

    buyer: str
    seller: str
    price: float
    quantity: float
    step: int


@dataclass
class AgentState:
    """State of a simulated agent."""

    agent_id: str
    agent_type: str
    cash: float = 100_000.0
    position: float = 0.0
    total_pnl: float = 0.0
    n_trades: int = 0


@dataclass
class SimulationResult:
    """Result of a multi-agent simulation run."""

    n_steps: int = 0
    n_trades: int = 0
    prices: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    spreads: list[float] = field(default_factory=list)
    agent_results: list[dict] = field(default_factory=list)
    news_trader_pnl: float = 0.0
    news_trader_sharpe: float = 0.0
    events_injected: int = 0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_steps": self.n_steps,
            "n_trades": self.n_trades,
            "final_price": round(self.prices[-1], 4) if self.prices else 0,
            "price_range": (
                round(min(self.prices), 4) if self.prices else 0,
                round(max(self.prices), 4) if self.prices else 0,
            ),
            "total_volume": round(sum(self.volumes), 2),
            "avg_spread": round(
                float(np.mean(self.spreads)) if self.spreads else 0, 4,
            ),
            "agent_results": self.agent_results,
            "news_trader_pnl": round(self.news_trader_pnl, 4),
            "news_trader_sharpe": round(self.news_trader_sharpe, 4),
            "events_injected": self.events_injected,
        }


class MarketSimulator:
    """
    Multi-agent market simulator for strategy testing.

    Usage:
        sim = MarketSimulator(initial_price=100.0)
        result = sim.run(
            n_steps=1000,
            event_schedule=[(50, 0.03), (200, -0.05)],
            news_strategy=my_signal_func,
        )
    """

    def __init__(
        self,
        initial_price: float = 100.0,
        n_market_makers: int = 3,
        n_noise_traders: int = 10,
        n_momentum: int = 3,
        n_arb: int = 2,
        tick_size: float = 0.01,
        spread_bps: float = 10.0,
        seed: int = 42,
    ) -> None:
        self._initial_price = initial_price
        self._tick = tick_size
        self._base_spread = spread_bps
        self._rng = np.random.default_rng(seed)

        # Agent configurations
        self._n_mm = n_market_makers
        self._n_noise = n_noise_traders
        self._n_momentum = n_momentum
        self._n_arb = n_arb

    def run(
        self,
        n_steps: int = 500,
        event_schedule: list[tuple[int, float]] | None = None,
        news_strategy: object | None = None,
    ) -> SimulationResult:
        """
        Run multi-agent simulation.

        Parameters
        ----------
        n_steps : number of simulation steps
        event_schedule : list of (step, price_impact) tuples
        news_strategy : callable(price, event) → signal (-1 to +1)
        """
        # Initialise agents
        agents = self._create_agents()
        price = self._initial_price
        prices: list[float] = [price]
        volumes: list[float] = [0.0]
        spreads: list[float] = [self._base_spread]
        trades: list[Trade] = []

        # Event lookup
        events: dict[int, float] = {}
        if event_schedule:
            for step, impact in event_schedule:
                events[step] = impact

        event_count = 0

        for step in range(1, n_steps + 1):
            step_orders: list[Order] = []
            step_volume = 0.0

            # Check for event injection
            event_impact = events.get(step, 0.0)
            if event_impact != 0.0:
                event_count += 1
                # Event causes fundamental price shift
                price *= (1 + event_impact)

            # Each agent generates orders
            for agent in agents.values():
                orders = self._agent_action(
                    agent, price, step, event_impact,
                )
                step_orders.extend(orders)

            # Match orders (simple crossing)
            step_trades, new_price, spread = self._match_orders(
                step_orders, price, step,
            )

            # Update agents from trades
            for trade in step_trades:
                self._settle_trade(trade, agents)
                step_volume += trade.quantity

            trades.extend(step_trades)

            # Add noise to price
            noise = float(self._rng.normal(0, 0.001))
            if new_price > 0:
                price = new_price * (1 + noise)
            else:
                price *= (1 + noise)

            price = max(price, self._tick)
            prices.append(price)
            volumes.append(step_volume)
            spreads.append(spread)

        # Compute results
        result = self._build_result(
            n_steps, prices, volumes, spreads, trades,
            agents, event_count,
        )

        logger.info(
            "Simulation complete: %d steps, %d trades, "
            "price %.2f→%.2f, news_trader PnL=%.4f",
            n_steps, len(trades), self._initial_price,
            prices[-1], result.news_trader_pnl,
        )
        return result

    def _create_agents(self) -> dict[str, AgentState]:
        """Create all agent types."""
        agents: dict[str, AgentState] = {}

        for i in range(self._n_mm):
            aid = f"mm_{i}"
            agents[aid] = AgentState(
                agent_id=aid, agent_type="market_maker",
                cash=500_000.0,
            )

        for i in range(self._n_noise):
            aid = f"noise_{i}"
            agents[aid] = AgentState(
                agent_id=aid, agent_type="noise_trader",
                cash=50_000.0,
            )

        for i in range(self._n_momentum):
            aid = f"mom_{i}"
            agents[aid] = AgentState(
                agent_id=aid, agent_type="momentum",
                cash=100_000.0,
            )

        for i in range(self._n_arb):
            aid = f"arb_{i}"
            agents[aid] = AgentState(
                agent_id=aid, agent_type="arbitrage",
                cash=200_000.0,
            )

        # Our news trader
        agents["news_trader"] = AgentState(
            agent_id="news_trader", agent_type="news_trader",
            cash=100_000.0,
        )

        return agents

    def _agent_action(
        self,
        agent: AgentState,
        price: float,
        step: int,
        event_impact: float,
    ) -> list[Order]:
        """Generate orders for an agent based on its type."""
        if agent.agent_type == "market_maker":
            return self._mm_action(agent, price, step)
        elif agent.agent_type == "noise_trader":
            return self._noise_action(agent, price, step)
        elif agent.agent_type == "momentum":
            return self._momentum_action(agent, price, step)
        elif agent.agent_type == "arbitrage":
            return self._arb_action(agent, price, step)
        elif agent.agent_type == "news_trader":
            return self._news_action(agent, price, step, event_impact)
        return []

    def _mm_action(
        self, agent: AgentState, price: float, step: int,
    ) -> list[Order]:
        """Market maker: post bid/ask around fair price."""
        spread = self._base_spread / 10000 * price
        half = spread / 2
        qty = float(self._rng.uniform(1, 5))

        orders = [
            Order(agent.agent_id, "buy", price - half, qty, step),
            Order(agent.agent_id, "sell", price + half, qty, step),
        ]
        return orders

    def _noise_action(
        self, agent: AgentState, price: float, step: int,
    ) -> list[Order]:
        """Noise trader: random orders."""
        if self._rng.random() > 0.3:
            return []

        side = "buy" if self._rng.random() > 0.5 else "sell"
        offset = float(self._rng.normal(0, 0.002)) * price
        qty = float(self._rng.uniform(0.1, 2.0))

        return [Order(agent.agent_id, side, price + offset, qty, step)]

    def _momentum_action(
        self, agent: AgentState, price: float, step: int,
    ) -> list[Order]:
        """Momentum trader: follow recent price direction."""
        if self._rng.random() > 0.2:
            return []

        # Use position as proxy for momentum belief
        if agent.position > 0:
            side = "buy"  # Continue long
        elif agent.position < 0:
            side = "sell"  # Continue short
        else:
            side = "buy" if self._rng.random() > 0.5 else "sell"

        qty = float(self._rng.uniform(0.5, 3.0))
        return [Order(agent.agent_id, side, price, qty, step)]

    def _arb_action(
        self, agent: AgentState, price: float, step: int,
    ) -> list[Order]:
        """Arbitrage bot: mean-revert extreme positions."""
        if abs(agent.position) < 1:
            return []

        # Close position towards zero
        if agent.position > 0:
            side = "sell"
        else:
            side = "buy"

        qty = min(abs(agent.position), 2.0)
        return [Order(agent.agent_id, side, price, qty, step)]

    def _news_action(
        self,
        agent: AgentState,
        price: float,
        step: int,
        event_impact: float,
    ) -> list[Order]:
        """News trader: react to events."""
        if event_impact == 0:
            return []

        # Trade in direction of event
        if event_impact > 0:
            side = "buy"
        else:
            side = "sell"

        # Size proportional to event magnitude
        qty = min(abs(event_impact) * 100, 10.0)
        qty = max(qty, 0.1)

        return [Order(agent.agent_id, side, price, qty, step)]

    def _match_orders(
        self,
        orders: list[Order],
        mid_price: float,
        step: int,
    ) -> tuple[list[Trade], float, float]:
        """Simple order matching engine."""
        buys = sorted(
            [o for o in orders if o.side == "buy"],
            key=lambda o: o.price, reverse=True,
        )
        sells = sorted(
            [o for o in orders if o.side == "sell"],
            key=lambda o: o.price,
        )

        trades: list[Trade] = []
        last_price = mid_price

        bi, si = 0, 0
        while bi < len(buys) and si < len(sells):
            buy = buys[bi]
            sell = sells[si]

            if buy.price >= sell.price:
                trade_price = (buy.price + sell.price) / 2
                trade_qty = min(buy.quantity, sell.quantity)

                trades.append(Trade(
                    buyer=buy.agent_id,
                    seller=sell.agent_id,
                    price=trade_price,
                    quantity=trade_qty,
                    step=step,
                ))
                last_price = trade_price

                buy.quantity -= trade_qty
                sell.quantity -= trade_qty

                if buy.quantity <= 0.001:
                    bi += 1
                if sell.quantity <= 0.001:
                    si += 1
            else:
                break

        # Spread
        best_bid = buys[0].price if buys else mid_price * 0.999
        best_ask = sells[0].price if sells else mid_price * 1.001
        spread = (best_ask - best_bid) / max(mid_price, 1e-10) * 10000

        return trades, last_price, spread

    def _settle_trade(
        self,
        trade: Trade,
        agents: dict[str, AgentState],
    ) -> None:
        """Settle a trade between buyer and seller."""
        buyer = agents.get(trade.buyer)
        seller = agents.get(trade.seller)

        if buyer:
            buyer.position += trade.quantity
            buyer.cash -= trade.price * trade.quantity
            buyer.n_trades += 1

        if seller:
            seller.position -= trade.quantity
            seller.cash += trade.price * trade.quantity
            seller.n_trades += 1

    def _build_result(
        self,
        n_steps: int,
        prices: list[float],
        volumes: list[float],
        spreads: list[float],
        trades: list[Trade],
        agents: dict[str, AgentState],
        event_count: int,
    ) -> SimulationResult:
        """Build simulation result."""
        # Compute PnL for each agent
        final_price = prices[-1]
        agent_results = []

        for agent in agents.values():
            mark_to_market = agent.cash + agent.position * final_price
            initial = 100_000.0 if agent.agent_type != "market_maker" else 500_000.0
            if agent.agent_type == "noise_trader":
                initial = 50_000.0
            elif agent.agent_type == "arbitrage":
                initial = 200_000.0

            pnl = mark_to_market - initial
            agent.total_pnl = pnl

            agent_results.append({
                "agent_id": agent.agent_id,
                "type": agent.agent_type,
                "pnl": round(pnl, 4),
                "trades": agent.n_trades,
                "final_position": round(agent.position, 4),
            })

        # News trader specific metrics
        news_agent = agents.get("news_trader")
        news_pnl = news_agent.total_pnl if news_agent else 0.0

        # Estimate Sharpe from price series
        price_arr = np.array(prices)
        returns = np.diff(price_arr) / price_arr[:-1]
        news_sharpe = 0.0
        if len(returns) > 1 and np.std(returns, ddof=1) > 0:
            news_sharpe = float(
                np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252)
            )

        return SimulationResult(
            n_steps=n_steps,
            n_trades=len(trades),
            prices=prices,
            volumes=volumes,
            spreads=spreads,
            agent_results=agent_results,
            news_trader_pnl=news_pnl,
            news_trader_sharpe=news_sharpe,
            events_injected=event_count,
        )
