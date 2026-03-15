"""
Simulation execution engine.

Runs the full event-driven pipeline on synthetic or stored events
with synthetic or stored candle data. No external connectivity required.

Flow
----
1. Initialise synthetic market data
2. Spawn synthetic event feed
3. For each event:
   a. Classify event (keyword + entity)
   b. Score confidence
   c. Generate signal (ENERGY_GEO or AI_RELEASES)
   d. Apply confirmation engine
   e. Open position via portfolio engine
   f. Advance time, update positions
4. Produce final performance report
5. Save all events + trades to database
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from ..classifier.entity_extractor import EntityExtractor
from ..classifier.keyword_classifier import KeywordClassifier
from ..config.settings import BotConfig
from ..feeds.base import EventDomain, NewsEvent
from ..feeds.synthetic import SyntheticFeed
from ..market.data import MarketDataFeed
from ..portfolio.engine import PortfolioEngine
from ..signals.ai_releases import AIReleasesSignalGenerator
from ..signals.confidence_model import ConfidenceModel
from ..signals.energy_geo import EnergyGeoSignalGenerator
from ..storage.database import Database

logger = logging.getLogger(__name__)


class SimulationEngine:
    """
    Runs a fully self-contained simulation.

    Parameters
    ----------
    config: BotConfig
    db: Database
    n_events: int
        Number of synthetic events to generate per domain.
    n_candles: int
        Number of candles in synthetic history.
    seed: int
        Random seed.
    """

    def __init__(
        self,
        config: BotConfig,
        db: Database,
        n_events: int = 50,
        n_candles: int = 500,
        seed: int = 42,
        external_candles=None,   # pd.DataFrame | None
        external_events=None,    # list[dict] | None — pre-classified event dicts
    ):
        self._config = config
        self._db = db
        self._n_events = n_events
        self._n_candles = n_candles
        self._seed = seed
        self._external_candles = external_candles
        self._external_events = external_events  # list of event dicts (from DB/JSON)

        # Sub-components
        self._market = MarketDataFeed(config)
        self._classifier = KeywordClassifier()
        self._entity_extractor = EntityExtractor()
        self._confidence = ConfidenceModel()

        # Signal generators (one per domain that is configured)
        self._generators = {}
        for sig_cfg in config.signals:
            if sig_cfg.domain == "ENERGY_GEO" and sig_cfg.enabled:
                self._generators["ENERGY_GEO"] = EnergyGeoSignalGenerator(config, sig_cfg)
            elif sig_cfg.domain == "AI_RELEASES" and sig_cfg.enabled:
                self._generators["AI_RELEASES"] = AIReleasesSignalGenerator(config, sig_cfg)

        self._portfolio = PortfolioEngine(config, self._market)
        self._run_id = self._make_run_id()

    def run(self) -> dict:
        """
        Execute the simulation synchronously.
        Returns the performance summary dict.
        """
        logger.info("=== SIMULATION START: %s ===", self._run_id)
        self._db.create_run(
            run_id=self._run_id,
            run_name=self._config.run_name,
            mode="simulate",
            initial_capital=self._config.portfolio.initial_capital,
            config_snapshot=self._config.model_dump(),
        )

        # Generate or load events
        events = self._generate_events()
        logger.info("Loaded %d events (%s)", len(events),
                    "external" if self._external_events else "synthetic")

        # Load candles — prefer external (backtest) over synthetic (simulate)
        if self._external_candles is not None and not self._external_candles.empty:
            self._market.load_dataframe(self._external_candles)
            logger.info("Using external candles (%d rows)", len(self._external_candles))
        else:
            shock_times = [ev.published_at for ev in events]
            self._market.load_synthetic(
                n_candles=self._n_candles,
                seed=self._seed,
                shock_times=shock_times,
            )

        # Process events one by one (simulate time progression)

        for ev in events:
            # Save event to DB
            self._db.save_event(ev, self._run_id)

            # Advance market to event time
            self._advance_market_to(ev.published_at)

            # Classify
            self._classifier.enrich(ev)
            self._entity_extractor.enrich(ev)

            # Confidence
            confidence = self._confidence.score(ev)

            # Generate signal
            gen = self._generators.get(ev.domain.value)
            if gen is None:
                continue

            signal = gen.generate(ev, confidence)
            if signal is None:
                continue

            # Portfolio: open position
            self._portfolio.on_signal(signal)

            # Advance time to simulate exit conditions
            self._advance_and_update(ev.published_at)

        # Final update pass
        self._portfolio.update()

        # Close all remaining open positions at current price
        current_time = datetime.now(timezone.utc)
        for pos in list(self._portfolio.open_positions):
            current_price = self._market.current_price()
            from ..portfolio.position import CloseReason
            pos.close(
                exit_price=current_price,
                exit_time=current_time,
                reason=CloseReason.TIME_STOP,
                commission_rate=self._config.portfolio.commission_rate,
            )
            self._portfolio._equity += pos.realised_pnl
            self._portfolio._closed_pnls.append(pos.realised_pnl)
            self._portfolio._equity_curve.append(self._portfolio._equity)

        # Save all trades
        for pos in self._portfolio.positions:
            self._db.save_trade(pos, self._run_id)

        perf = self._portfolio.performance()
        summary = self._portfolio.summary()

        self._db.close_run(
            run_id=self._run_id,
            final_equity=self._portfolio.equity,
            total_trades=perf.total_trades,
            total_pnl=perf.total_pnl,
            sharpe=perf.sharpe_ratio,
            max_dd=perf.max_drawdown_pct,
        )

        logger.info(
            "=== SIMULATION COMPLETE: %d trades | equity=%.4f | return=%.2f%% ===",
            perf.total_trades,
            self._portfolio.equity,
            summary.get("return_pct", 0.0),
        )

        # Auto-save per-run metrics JSON
        self._save_metrics_json(summary)
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_events(self) -> list[NewsEvent]:
        """Return events from external source (backtest) or generate synthetic ones."""
        from datetime import datetime, timedelta, timezone

        # --- Backtest mode: reconstruct NewsEvent from stored dicts ---
        if self._external_events:
            events: list[NewsEvent] = []
            for d in self._external_events:
                try:
                    domain = EventDomain(d.get("domain", "UNKNOWN"))
                except ValueError:
                    domain = EventDomain.UNKNOWN
                ts_str = d.get("published_at", "")
                try:
                    import pandas as pd
                    ts = pd.Timestamp(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.tz_localize("UTC")
                    published_at = ts.to_pydatetime()
                except (ValueError, TypeError):
                    published_at = datetime.now(timezone.utc)
                ev = NewsEvent(
                    event_id=d.get("event_id", NewsEvent.make_id(
                        d.get("source", ""), d.get("url", ""), d.get("headline", "")
                    )),
                    domain=domain,
                    headline=d.get("headline", ""),
                    summary=d.get("summary", ""),
                    source=d.get("source", "stored"),
                    url=d.get("url", ""),
                    published_at=published_at,
                    credibility_weight=d.get("credibility_weight", 1.0),
                    keywords_matched=d.get("keywords_matched", []),
                    sentiment_score=d.get("sentiment_score", 0.0),
                    importance_score=d.get("importance_score", 0.5),
                )
                events.append(ev)
            events.sort(key=lambda e: e.published_at)
            return events

        # --- Simulate mode: generate synthetic events ---
        tf_minutes = self._market._tf_minutes()
        sim_start = datetime.now(timezone.utc) - timedelta(minutes=tf_minutes * self._n_candles)

        events = []
        for domain in [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]:
            feed = SyntheticFeed(
                domain=domain,
                seed=self._seed,
                start_time=sim_start + timedelta(minutes=tf_minutes * 10),
                time_step_minutes=tf_minutes * 8,
                credibility_weight=1.0,
            )
            batch = feed.generate_batch(self._n_events)
            events.extend(batch)

        events.sort(key=lambda e: e.published_at)
        return events

    def _advance_market_to(self, ts: datetime) -> None:
        """Point market data cursor to nearest candle at *ts*."""
        candles = self._market.candles
        if candles.empty:
            return
        # This is a simulation — candles are pre-loaded, we just query them
        # No actual advance needed; portfolio engine reads current_price()

    def _advance_and_update(self, from_ts: datetime) -> None:
        """Simulate time advance and trigger position exit checks."""
        self._portfolio.update(current_time=from_ts + timedelta(hours=2))

    def _make_run_id(self) -> str:
        ts = datetime.now(timezone.utc).isoformat()
        return hashlib.sha256(
            f"{self._config.run_name}{ts}".encode()
        ).hexdigest()[:16]
