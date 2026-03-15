"""
Shared in-memory application state for the web API.
Thread-safe via asyncio.Lock.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class EventEntry:
    id: str
    timestamp: str
    domain: str
    headline: str
    summary: str
    sentiment: float
    importance: float
    direction: str
    confidence: float
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TradeEntry:
    id: str
    opened_at: str
    closed_at: str | None
    symbol: str
    direction: str
    size_eur: float
    entry_price: float
    exit_price: float | None
    pnl_eur: float
    pnl_pct: float
    status: str
    event_headline: str
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return asdict(self)


class AppState:
    """Central state shared between the trading engine and REST/WS endpoints."""

    def __init__(self, initial_capital: float = 500.0):
        self.initial_capital: float = initial_capital
        self.balance: float = initial_capital
        self.peak_balance: float = initial_capital
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.events: list[EventEntry] = []
        self.trades: list[TradeEntry] = []
        self.open_positions: dict[str, TradeEntry] = {}
        self.running: bool = False
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self._lock = asyncio.Lock()
        self._ws_clients: set = set()

        # Equity curve: [{ts, balance}] kept to 1000 points
        self.equity_curve: list[dict] = [
            {"ts": self.started_at, "balance": initial_capital}
        ]

        # Live prices synced from engine each tick
        self.prices: dict[str, float] = {
            "BTC/USDT": 65_000.0,
            "ETH/USDT": 3_500.0,
        }

        # Runtime config — can be patched via /api/config without restart
        self.config: dict[str, Any] = {
            "initial_capital": initial_capital,
            "tick_interval": 25.0,
            "risk_pct": 0.02,
            "min_confidence": 0.40,
            "max_positions": 3,
        }

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def total_pnl(self) -> float:
        return round(self.balance - self.initial_capital, 2)

    @property
    def total_pnl_pct(self) -> float:
        return round((self.total_pnl / self.initial_capital) * 100, 2)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_balance <= 0:
            return 0.0
        return round((1 - self.balance / self.peak_balance) * 100, 2)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return round((self.winning_trades / self.total_trades) * 100, 1)

    @property
    def profit_factor(self) -> float | None:
        wins = sum(t.pnl_eur for t in self.trades if t.pnl_eur > 0)
        losses = abs(sum(t.pnl_eur for t in self.trades if t.pnl_eur <= 0))
        if losses == 0:
            return None
        return round(wins / losses, 3)

    @property
    def avg_trade_pnl(self) -> float:
        if not self.trades:
            return 0.0
        return round(sum(t.pnl_eur for t in self.trades) / len(self.trades), 2)

    def record_equity(self) -> None:
        """Append current balance to the equity curve after a balance change."""
        self.equity_curve.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "balance": round(self.balance, 2),
        })
        if len(self.equity_curve) > 1000:
            self.equity_curve = self.equity_curve[-1000:]

    def summary(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "started_at": self.started_at,
            "initial_capital": self.initial_capital,
            "balance": round(self.balance, 2),
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "peak_balance": round(self.peak_balance, 2),
            "drawdown_pct": self.drawdown_pct,
            "total_trades": self.total_trades,
            "open_positions": len(self.open_positions),
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_trade_pnl": self.avg_trade_pnl,
            "prices": dict(self.prices),
            "config": dict(self.config),
        }

    # ------------------------------------------------------------------
    # WebSocket broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, msg: dict[str, object]) -> None:
        """Send *msg* to all connected WebSocket clients; remove dead sockets."""
        dead: set = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_json(msg)
            except (ConnectionError, RuntimeError):
                dead.add(ws)
        self._ws_clients -= dead

    def add_ws_client(self, ws: object) -> None:
        """Register a new WebSocket client for broadcast updates."""
        self._ws_clients.add(ws)

    def remove_ws_client(self, ws: object) -> None:
        """Unregister a WebSocket client (safe if not present)."""
        self._ws_clients.discard(ws)
