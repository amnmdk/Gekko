"""
Paper trading execution engine.

Safety guarantees
-----------------
1. DRY_RUN is True by default — no real orders submitted without explicit config.
2. Sandbox/testnet mode is required by default.
3. If sandbox is unavailable and require_sandbox=True, execution is REFUSED.
4. All order submissions are logged with full audit trail.
5. Paper mode uses CCXT with testnet credentials only.

Architecture
------------
- Runs an async event loop
- Polls live candles from exchange every candle interval
- Polls configured RSS feeds for real news events
- Processes events through the full signal pipeline
- Submits orders to testnet (or logs them in DRY_RUN mode)
- Updates positions on every candle close
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from ..classifier.entity_extractor import EntityExtractor
from ..classifier.keyword_classifier import KeywordClassifier
from ..config.settings import BotConfig
from ..feeds.base import NewsEvent
from ..feeds.manager import FeedManager
from ..market.data import MarketDataFeed
from ..portfolio.engine import PortfolioEngine
from ..portfolio.position import Position
from ..signals.ai_releases import AIReleasesSignalGenerator
from ..signals.confidence_model import ConfidenceModel
from ..signals.energy_geo import EnergyGeoSignalGenerator
from ..storage.database import Database

logger = logging.getLogger(__name__)

# Safety banner printed on startup
_PAPER_BANNER = """
╔══════════════════════════════════════════════════════╗
║          ndbot — PAPER TRADING MODE                  ║
║  DRY_RUN: {dry_run:<5}  │  SANDBOX: {sandbox:<5}             ║
║  Exchange: {exchange:<20}                  ║
║  Symbol:   {symbol:<20}                  ║
║  WARNING: Paper mode only. No real funds at risk.    ║
╚══════════════════════════════════════════════════════╝
"""


class PaperEngine:
    """
    Async paper trading engine.

    Parameters
    ----------
    config: BotConfig
    db: Database
    """

    def __init__(self, config: BotConfig, db: Database):
        self._config = config
        self._db = db
        self._market = MarketDataFeed(config)
        self._feed_manager = FeedManager(config)
        self._classifier = KeywordClassifier()
        self._entity_extractor = EntityExtractor()
        self._confidence = ConfidenceModel()
        self._generators = {}
        for sig_cfg in config.signals:
            if sig_cfg.domain == "ENERGY_GEO" and sig_cfg.enabled:
                self._generators["ENERGY_GEO"] = EnergyGeoSignalGenerator(config, sig_cfg)
            elif sig_cfg.domain == "AI_RELEASES" and sig_cfg.enabled:
                self._generators["AI_RELEASES"] = AIReleasesSignalGenerator(config, sig_cfg)
        self._portfolio = PortfolioEngine(config, self._market)
        self._run_id = self._make_run_id()
        self._running = False

    async def run(self, duration_seconds: Optional[int] = None) -> dict:
        """
        Run the paper trading engine.

        Parameters
        ----------
        duration_seconds: int | None
            How long to run. None = run indefinitely until interrupted.
        """
        self._print_banner()
        self._safety_check()

        logger.info("Initialising exchange connection...")
        await self._market.init_paper()

        self._db.create_run(
            run_id=self._run_id,
            run_name=self._config.run_name,
            mode="paper",
            initial_capital=self._config.portfolio.initial_capital,
            config_snapshot=self._config.model_dump(),
        )

        self._feed_manager.on_event(self._on_event)
        self._running = True

        tasks = [
            asyncio.create_task(self._feed_manager.run(), name="feeds"),
            asyncio.create_task(self._candle_loop(), name="candles"),
            asyncio.create_task(self._position_monitor_loop(), name="positions"),
        ]

        if duration_seconds is not None:
            tasks.append(
                asyncio.create_task(
                    asyncio.sleep(duration_seconds), name="timer"
                )
            )
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        else:
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    t.cancel()

        return await self._shutdown()

    async def _on_event(self, event: NewsEvent) -> None:
        """Handle an incoming live news event."""
        self._db.save_event(event, self._run_id)

        # Classify
        self._classifier.enrich(event)
        self._entity_extractor.enrich(event)

        # Confidence
        confidence = self._confidence.score(event)

        # Signal
        gen = self._generators.get(event.domain.value)
        if gen is None:
            return
        signal = gen.generate(event, confidence)
        if signal is None:
            return

        # Portfolio
        position = self._portfolio.on_signal(signal)
        if position is not None:
            await self._submit_order(position)

    async def _submit_order(self, position: Position) -> None:
        """
        Submit order to exchange testnet, or log in DRY_RUN mode.
        """
        dry_run = self._config.paper.dry_run
        if dry_run:
            logger.info(
                "[DRY_RUN] ORDER: %s %s %s @ %.4f | size=%.6f",
                position.direction, position.symbol, position.position_id,
                position.entry_price, position.size,
            )
            return

        # Real testnet submission via CCXT
        if self._market._exchange is None:
            logger.warning("Exchange not initialised — order not submitted")
            return
        try:
            side = "buy" if position.direction == "LONG" else "sell"
            order = await self._market._exchange.create_market_order(
                position.symbol, side, position.size
            )
            logger.info(
                "TESTNET ORDER SUBMITTED: %s | order_id=%s",
                position.position_id, order.get("id", "?"),
            )
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            logger.error("Order submission failed: %s", exc)

    async def _candle_loop(self) -> None:
        """Refresh candles on each new candle close."""
        tf_minutes = self._market._tf_minutes()
        interval = tf_minutes * 60  # seconds
        while self._running:
            await asyncio.sleep(interval)
            await self._market.refresh_candles()
            logger.debug("Candles refreshed")

    async def _position_monitor_loop(self) -> None:
        """Check positions for exits every 30 seconds."""
        while self._running:
            await asyncio.sleep(30)
            closed = self._portfolio.update()
            for pos in closed:
                self._db.save_trade(pos, self._run_id)
                if not self._config.paper.dry_run:
                    await self._close_exchange_position(pos)

    async def _close_exchange_position(self, position: Position) -> None:
        """Submit a closing order to the exchange for *position*."""
        if self._market._exchange is None:
            return
        try:
            side = "sell" if position.direction == "LONG" else "buy"
            await self._market._exchange.create_market_order(
                position.symbol, side, position.size
            )
            logger.info("Exchange close order for position %s", position.position_id)
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            logger.error("Close order failed for %s: %s", position.position_id, exc)

    async def _shutdown(self) -> dict:
        """Gracefully shut down the engine: save trades, close exchange, return summary."""
        self._running = False
        for pos in self._portfolio.open_positions:
            self._db.save_trade(pos, self._run_id)
        perf = self._portfolio.performance()
        self._db.close_run(
            run_id=self._run_id,
            final_equity=self._portfolio.equity,
            total_trades=perf.total_trades,
            total_pnl=perf.total_pnl,
            sharpe=perf.sharpe_ratio,
            max_dd=perf.max_drawdown_pct,
        )
        await self._market.close()
        summary = self._portfolio.summary()
        self._save_metrics_json(summary)
        logger.info("Paper engine shutdown complete.")
        return summary

    def _save_metrics_json(self, summary: dict) -> None:
        """Save run metrics to results/run_{run_id}_metrics.json."""
        import json
        from pathlib import Path
        results_dir = Path("results")
        results_dir.mkdir(parents=True, exist_ok=True)
        out = results_dir / f"run_{self._run_id}_metrics.json"
        with open(out, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info("Run metrics saved: %s", out)

    def _safety_check(self) -> None:
        """Hard safety check before any exchange connectivity."""
        cfg = self._config.paper
        if not cfg.dry_run and not cfg.require_sandbox:
            raise RuntimeError(
                "SAFETY VIOLATION: Both dry_run=False AND require_sandbox=False. "
                "This configuration could submit REAL orders. "
                "Set dry_run=True or require_sandbox=True to proceed."
            )
        logger.info(
            "Paper safety check passed: dry_run=%s, require_sandbox=%s",
            cfg.dry_run, cfg.require_sandbox,
        )

    def _print_banner(self) -> None:
        """Print the safety banner showing DRY_RUN and SANDBOX status."""
        cfg = self._config.paper
        print(_PAPER_BANNER.format(
            dry_run=str(cfg.dry_run),
            sandbox=str(cfg.require_sandbox),
            exchange=cfg.exchange_id,
            symbol=self._config.market.symbol,
        ))

    def _make_run_id(self) -> str:
        """Generate a deterministic short run ID from config name and timestamp."""
        ts = datetime.now(timezone.utc).isoformat()
        return hashlib.sha256(
            f"paper_{self._config.run_name}{ts}".encode()
        ).hexdigest()[:16]
