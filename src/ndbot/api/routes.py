"""REST API routes for the ndbot web dashboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .state import AppState

router = APIRouter()
_state: AppState | None = None


def init_routes(state: AppState) -> None:
    global _state
    _state = state


def _get_state() -> AppState:
    if _state is None:
        raise HTTPException(500, "State not initialised")
    return _state


@router.get("/status")
async def get_status():
    return _get_state().summary()


@router.get("/balance")
async def get_balance():
    s = _get_state()
    return {
        "balance": round(s.balance, 2),
        "initial_capital": s.initial_capital,
        "total_pnl": s.total_pnl,
        "total_pnl_pct": s.total_pnl_pct,
        "peak_balance": round(s.peak_balance, 2),
        "drawdown_pct": s.drawdown_pct,
        "currency": "EUR",
    }


@router.get("/events")
async def get_events(limit: int = Query(default=50, ge=1, le=200)):
    s = _get_state()
    return [e.to_dict() for e in s.events[:limit]]


@router.get("/positions")
async def get_positions():
    s = _get_state()
    return [p.to_dict() for p in s.open_positions.values()]


@router.get("/trades")
async def get_trades(limit: int = Query(default=100, ge=1, le=500)):
    s = _get_state()
    return [t.to_dict() for t in s.trades[:limit]]


@router.get("/metrics")
async def get_metrics():
    s = _get_state()
    closed = s.trades
    if not closed:
        return {"message": "No closed trades yet", **s.summary()}

    pnls = [t.pnl_eur for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    return {
        **s.summary(),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(pnls), 2),
        "largest_loss": round(min(pnls), 2),
        "total_pnl_sum": round(sum(pnls), 2),
    }


@router.post("/reset")
async def reset_bot(capital: float = Query(default=500.0, ge=10.0, le=100_000.0)):
    """Reset balance to a new starting capital and clear trade history."""
    s = _get_state()
    async with s._lock:
        s.balance = capital
        s.initial_capital = capital
        s.peak_balance = capital
        s.total_trades = 0
        s.winning_trades = 0
        s.trades.clear()
        s.events.clear()
        s.open_positions.clear()
    await s.broadcast({"type": "reset", "data": s.summary()})
    return {"message": f"Bot reset. New balance: {capital:.2f} EUR"}
