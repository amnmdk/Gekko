"""
SQLAlchemy ORM models for ndbot persistent storage.

Tables:
  events            — all ingested and classified news events
  trades            — all opened and closed positions
  runs              — one row per bot run (session metadata)
  walkforward_results — per-window walk-forward validation results
  grid_results      — parameter grid search results
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    domain: Mapped[str] = mapped_column(String(32))
    headline: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime)
    ingested_at: Mapped[datetime] = mapped_column(DateTime)
    credibility_weight: Mapped[float] = mapped_column(Float, default=1.0)
    keywords_matched: Mapped[str] = mapped_column(Text, default="")  # JSON list
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    entities: Mapped[str] = mapped_column(Text, default="{}")  # JSON dict


class TradeRecord(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    domain: Mapped[str] = mapped_column(String(32))
    signal_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[str] = mapped_column(String(64))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    size: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime)
    exit_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    holding_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    close_reason: Mapped[str] = mapped_column(String(32), nullable=True)
    realised_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    commission_paid: Mapped[float] = mapped_column(Float, default=0.0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_name: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    initial_capital: Mapped[float] = mapped_column(Float)
    final_equity: Mapped[float] = mapped_column(Float, nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=True)
    config_snapshot: Mapped[str] = mapped_column(Text, default="{}")  # JSON


class WalkForwardResult(Base):
    __tablename__ = "walkforward_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    window_idx: Mapped[int] = mapped_column(Integer)
    train_start: Mapped[str] = mapped_column(String(32))
    train_end: Mapped[str] = mapped_column(String(32))
    test_start: Mapped[str] = mapped_column(String(32))
    test_end: Mapped[str] = mapped_column(String(32))
    best_min_confidence: Mapped[float] = mapped_column(Float)
    best_risk_per_trade: Mapped[float] = mapped_column(Float)
    is_sharpe: Mapped[float] = mapped_column(Float, nullable=True)
    oos_sharpe: Mapped[float] = mapped_column(Float, nullable=True)
    oos_return_pct: Mapped[float] = mapped_column(Float, nullable=True)
    oos_max_dd: Mapped[float] = mapped_column(Float, nullable=True)
    oos_trades: Mapped[int] = mapped_column(Integer, default=0)


class GridResult(Base):
    __tablename__ = "grid_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    min_confidence: Mapped[float] = mapped_column(Float)
    risk_per_trade: Mapped[float] = mapped_column(Float)
    total_trades: Mapped[int] = mapped_column(Integer)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[float] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=True)
    win_rate_pct: Mapped[float] = mapped_column(Float, nullable=True)
