"""
Database abstraction layer.

Clean interface over SQLAlchemy + SQLite.
All operations are synchronous (SQLite is fast enough for this workload;
no need for async overhead on Pi 5).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..feeds.base import NewsEvent
from ..portfolio.position import Position
from .models import (
    Base,
    EventRecord,
    GridResult,
    RunRecord,
    TradeRecord,
    WalkForwardResult,
)

logger = logging.getLogger(__name__)


class Database:
    """
    Thin abstraction over the SQLite database.

    Usage
    -----
    db = Database("data/ndbot.db")
    db.init()
    db.save_event(event)
    db.save_trade(position, run_id)
    """

    def __init__(self, db_path: str = "data/ndbot.db"):
        self._db_path = db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False)

    def init(self) -> None:
        """Create all tables if not already present."""
        Base.metadata.create_all(self._engine)
        logger.info("Database initialised: %s", self._db_path)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Dispose SQLAlchemy engine and release the SQLite file handle."""
        self._engine.dispose()

    def save_event(self, event: NewsEvent, run_id: str) -> None:
        """Persist a NewsEvent to the database (idempotent — skips duplicates)."""
        with self._Session() as session:
            existing = session.query(EventRecord).filter_by(
                event_id=event.event_id
            ).first()
            if existing:
                return  # Already stored
            record = EventRecord(
                event_id=event.event_id,
                run_id=run_id,
                domain=event.domain.value,
                headline=event.headline,
                summary=event.summary[:2000],
                source=event.source,
                url=event.url,
                published_at=event.published_at.replace(tzinfo=None),
                ingested_at=event.ingested_at.replace(tzinfo=None),
                credibility_weight=event.credibility_weight,
                keywords_matched=json.dumps(event.keywords_matched),
                sentiment_score=event.sentiment_score,
                importance_score=event.importance_score,
                entities=json.dumps(event.entities),
            )
            session.add(record)
            session.commit()

    def get_events(
        self,
        run_id: Optional[str] = None,
        domain: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Query stored events, optionally filtered by run_id and domain."""
        with self._Session() as session:
            q = session.query(EventRecord)
            if run_id:
                q = q.filter_by(run_id=run_id)
            if domain:
                q = q.filter_by(domain=domain)
            q = q.order_by(EventRecord.published_at.desc()).limit(limit)
            rows = q.all()
        return [self._event_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(self, position: Position, run_id: str) -> None:
        """Persist or update a Position as a TradeRecord in the database."""
        with self._Session() as session:
            existing = session.query(TradeRecord).filter_by(
                position_id=position.position_id
            ).first()
            record_data = dict(
                position_id=position.position_id,
                run_id=run_id,
                symbol=position.symbol,
                direction=position.direction,
                domain=position.domain,
                signal_id=position.signal_id,
                event_id="",
                entry_price=position.entry_price,
                exit_price=position.exit_price,
                size=position.size,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                entry_time=position.entry_time.replace(tzinfo=None),
                exit_time=(
                    position.exit_time.replace(tzinfo=None)
                    if position.exit_time else None
                ),
                holding_minutes=position.holding_minutes,
                status=position.status.value,
                close_reason=(
                    position.close_reason.value if position.close_reason else None
                ),
                realised_pnl=position.realised_pnl,
                commission_paid=position.commission_paid,
                risk_amount=position.risk_amount,
                confidence=position.confidence,
            )
            if existing:
                for k, v in record_data.items():
                    setattr(existing, k, v)
            else:
                session.add(TradeRecord(**record_data))
            session.commit()

    def get_trades(
        self, run_id: Optional[str] = None, limit: int = 500
    ) -> list[dict]:
        """Query stored trades, optionally filtered by run_id."""
        with self._Session() as session:
            q = session.query(TradeRecord)
            if run_id:
                q = q.filter_by(run_id=run_id)
            q = q.order_by(TradeRecord.entry_time.desc()).limit(limit)
            rows = q.all()
        return [self._trade_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        run_name: str,
        mode: str,
        initial_capital: float,
        config_snapshot: dict,
    ) -> None:
        """Insert a new run record at the start of a simulation or paper session."""
        with self._Session() as session:
            record = RunRecord(
                run_id=run_id,
                run_name=run_name,
                mode=mode,
                start_time=datetime.now(timezone.utc).replace(tzinfo=None),
                initial_capital=initial_capital,
                config_snapshot=json.dumps(config_snapshot, default=str),
            )
            session.add(record)
            session.commit()
        logger.info("Run created: %s", run_id)

    def close_run(
        self,
        run_id: str,
        final_equity: float,
        total_trades: int,
        total_pnl: float,
        sharpe: Optional[float],
        max_dd: Optional[float],
    ) -> None:
        """Finalise a run record with end-of-run performance metrics."""
        with self._Session() as session:
            record = session.query(RunRecord).filter_by(run_id=run_id).first()
            if record:
                record.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
                record.final_equity = final_equity
                record.total_trades = total_trades
                record.total_pnl = total_pnl
                record.sharpe_ratio = sharpe
                record.max_drawdown_pct = max_dd
                session.commit()

    def get_runs(self, limit: int = 50) -> list[dict]:
        """Return recent runs sorted by start time descending."""
        with self._Session() as session:
            rows = (
                session.query(RunRecord)
                .order_by(RunRecord.start_time.desc())
                .limit(limit)
                .all()
            )
        return [self._run_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Walk-forward results
    # ------------------------------------------------------------------

    def save_walkforward_result(self, run_id: str, window: dict) -> None:
        """Persist a single walk-forward window result."""
        oos = window.get("oos", {})
        is_ = window.get("in_sample", {})
        bp = window.get("best_params", {})
        with self._Session() as session:
            record = WalkForwardResult(
                run_id=run_id,
                window_idx=window.get("window_idx", 0),
                train_start=window.get("train_start", ""),
                train_end=window.get("train_end", ""),
                test_start=window.get("test_start", ""),
                test_end=window.get("test_end", ""),
                best_min_confidence=bp.get("min_confidence", 0.0),
                best_risk_per_trade=bp.get("risk_per_trade", 0.0),
                is_sharpe=is_.get("sharpe_ratio"),
                oos_sharpe=oos.get("sharpe_ratio"),
                oos_return_pct=oos.get("total_return_pct"),
                oos_max_dd=oos.get("max_drawdown_pct"),
                oos_trades=oos.get("total_trades", 0),
            )
            session.add(record)
            session.commit()

    # ------------------------------------------------------------------
    # Grid results
    # ------------------------------------------------------------------

    def save_grid_result(self, run_id: str, params: dict, metrics: dict) -> None:
        """Persist a single grid search parameter combination result."""
        with self._Session() as session:
            record = GridResult(
                run_id=run_id,
                min_confidence=params.get("min_confidence", 0.0),
                risk_per_trade=params.get("risk_per_trade", 0.0),
                total_trades=metrics.get("total_trades", 0),
                sharpe_ratio=metrics.get("sharpe_ratio"),
                total_return_pct=metrics.get("total_return_pct"),
                max_drawdown_pct=metrics.get("max_drawdown_pct"),
                profit_factor=metrics.get("profit_factor"),
                win_rate_pct=metrics.get("win_rate_pct"),
            )
            session.add(record)
            session.commit()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def execute_raw(self, sql: str) -> list[dict]:
        """Execute a raw SQL query and return results as a list of dicts."""
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            cols = list(result.keys())
            return [dict(zip(cols, row)) for row in result]

    # ------------------------------------------------------------------
    # Private serialisers
    # ------------------------------------------------------------------

    @staticmethod
    def _event_to_dict(r: EventRecord) -> dict:
        """Serialise an EventRecord ORM object to a plain dict."""
        return {
            "event_id": r.event_id,
            "run_id": r.run_id,
            "domain": r.domain,
            "headline": r.headline,
            "source": r.source,
            "published_at": str(r.published_at),
            "sentiment_score": r.sentiment_score,
            "importance_score": r.importance_score,
            "keywords_matched": json.loads(r.keywords_matched or "[]"),
        }

    @staticmethod
    def _trade_to_dict(r: TradeRecord) -> dict:
        """Serialise a TradeRecord ORM object to a plain dict."""
        return {
            "position_id": r.position_id,
            "run_id": r.run_id,
            "symbol": r.symbol,
            "direction": r.direction,
            "domain": r.domain,
            "entry_price": r.entry_price,
            "exit_price": r.exit_price,
            "size": r.size,
            "entry_time": str(r.entry_time),
            "exit_time": str(r.exit_time),
            "status": r.status,
            "close_reason": r.close_reason,
            "realised_pnl": r.realised_pnl,
            "confidence": r.confidence,
        }

    @staticmethod
    def _run_to_dict(r: RunRecord) -> dict:
        """Serialise a RunRecord ORM object to a plain dict."""
        return {
            "run_id": r.run_id,
            "run_name": r.run_name,
            "mode": r.mode,
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
            "initial_capital": r.initial_capital,
            "final_equity": r.final_equity,
            "total_trades": r.total_trades,
            "total_pnl": r.total_pnl,
            "sharpe_ratio": r.sharpe_ratio,
            "max_drawdown_pct": r.max_drawdown_pct,
        }
