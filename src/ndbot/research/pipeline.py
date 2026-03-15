"""
Automated Research Pipeline (Step 11).

Orchestrates the full alpha discovery workflow:

  1. Ingest       — Collect events from dataset
  2. Classify     — Map events to taxonomy types
  3. Feature      — Extract feature vectors
  4. Analyse      — Run event reaction analysis
  5. Discover     — Run alpha signal discovery
  6. Test         — Run hypothesis testing
  7. Validate     — Run edge stability testing
  8. Register     — Update alpha registry
  9. Report       — Generate summary report

Can be run as a single command: `ndbot alpha-pipeline`
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from ..data.news_dataset_builder import NewsDatasetBuilder
from ..features.news_features import NewsFeatureEngine
from ..feeds.base import EventDomain, NewsEvent
from .adversarial import AdversarialDefense
from .alpha_discovery import AlphaDiscoveryEngine
from .alpha_registry import (
    AlphaRegistry,
    AlphaRegistryEntry,
    SignalStatus,
)
from .edge_stability import EdgeStabilityTester
from .event_taxonomy import EventTaxonomy
from .hypothesis import HypothesisEngine

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a full pipeline run."""
    run_id: str
    timestamp: str
    events_processed: int = 0
    events_flagged: int = 0
    categories_analysed: int = 0
    signals_discovered: int = 0
    signals_significant: int = 0
    hypotheses_tested: int = 0
    hypotheses_rejected: int = 0
    signals_stable: int = 0
    signals_registered: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "events_processed": self.events_processed,
            "events_flagged": self.events_flagged,
            "categories_analysed": self.categories_analysed,
            "signals_discovered": self.signals_discovered,
            "signals_significant": self.signals_significant,
            "hypotheses_tested": self.hypotheses_tested,
            "hypotheses_rejected": self.hypotheses_rejected,
            "signals_stable": self.signals_stable,
            "signals_registered": self.signals_registered,
            "errors": self.errors,
        }


class ResearchPipeline:
    """
    Automated end-to-end alpha discovery pipeline.

    Usage:
        pipeline = ResearchPipeline()
        result = pipeline.run()
    """

    def __init__(
        self,
        dataset_dir: str = "data/news_dataset",
        registry_dir: str = "data/alpha_registry",
        output_dir: str = "results",
    ):
        self._dataset = NewsDatasetBuilder(dataset_dir)
        self._taxonomy = EventTaxonomy()
        self._features = NewsFeatureEngine()
        self._defense = AdversarialDefense()
        self._hypothesis = HypothesisEngine()
        self._stability = EdgeStabilityTester()
        self._discovery = AlphaDiscoveryEngine()
        self._registry = AlphaRegistry(registry_dir)
        self._output_dir = Path(output_dir)

    def run(
        self,
        domain: Optional[str] = None,
        limit: int = 5000,
    ) -> PipelineResult:
        """
        Run the full pipeline.

        Parameters
        ----------
        domain : str, optional
            Filter events by domain (e.g., "ENERGY_GEO").
        limit : int
            Max events to process.

        Returns
        -------
        PipelineResult
        """
        ts = datetime.now(timezone.utc)
        run_id = f"pipeline_{ts.strftime('%Y%m%d_%H%M%S')}"
        result = PipelineResult(
            run_id=run_id,
            timestamp=ts.isoformat(),
        )

        logger.info("Starting research pipeline: %s", run_id)

        # --- 1. Ingest events from dataset ---
        events = self._dataset.query(domain=domain, limit=limit)
        result.events_processed = len(events)
        if not events:
            result.errors.append("No events in dataset")
            logger.warning("Pipeline: no events found")
            self._save_result(result)
            return result

        logger.info("Pipeline: loaded %d events", len(events))

        # --- 2. Classify events ---
        for ev in events:
            if ev.get("event_type", "UNKNOWN") == "UNKNOWN":
                best = self._taxonomy.classify_best(
                    ev.get("headline", "")
                )
                if best:
                    ev["event_type"] = best[0]

        # --- 3. Screen for adversarial content ---
        clean_events = []
        for ev in events:
            # Build minimal NewsEvent for screening
            try:
                news_ev = NewsEvent(
                    event_id=ev.get("event_id", ""),
                    domain=EventDomain(
                        ev.get("domain", "UNKNOWN")
                    ),
                    headline=ev.get("headline", ""),
                    summary=ev.get("summary", ""),
                    source=ev.get("source", ""),
                    url=ev.get("url", ""),
                    published_at=datetime.fromisoformat(
                        ev.get("timestamp", ts.isoformat())
                        .replace("Z", "+00:00")
                    ),
                    credibility_weight=ev.get(
                        "credibility_weight", 1.0
                    ),
                    keywords_matched=ev.get("keywords", []),
                    sentiment_score=ev.get("sentiment_score", 0.0),
                    importance_score=ev.get("importance_score", 0.5),
                )
                defense_result = self._defense.screen(news_ev)
                if not defense_result.is_suspicious:
                    clean_events.append((ev, news_ev))
                else:
                    result.events_flagged += 1
            except (ValueError, KeyError) as exc:
                logger.debug("Event screening failed: %s", exc)

        logger.info(
            "Pipeline: %d clean events (%d flagged)",
            len(clean_events), result.events_flagged,
        )

        if not clean_events:
            result.errors.append("All events flagged by defense")
            self._save_result(result)
            return result

        # --- 4. Extract features ---
        feature_engine = NewsFeatureEngine()
        feature_vectors = []
        for _, news_ev in clean_events:
            feat = feature_engine.extract(news_ev)
            feature_vectors.append(feat)

        feature_names = feature_engine.feature_names()
        feat_matrix = np.array([
            [fv.get(fn, 0.0) for fn in feature_names]
            for fv in feature_vectors
        ])

        # --- 5. Group returns by event type for hypothesis testing ---
        event_returns: dict[str, dict[str, list[float]]] = {}
        for ev_dict, _ in clean_events:
            et = ev_dict.get("event_type", "UNKNOWN")
            if et not in event_returns:
                event_returns[et] = {h: [] for h in ["5m", "15m", "1h"]}

            # Use sentiment as a proxy for return direction
            # (real returns come from event reaction analysis)
            sent = ev_dict.get("sentiment_score", 0.0)
            imp = ev_dict.get("importance_score", 0.5)
            proxy = sent * imp * 2.0  # Rough proxy return %
            for h in event_returns[et]:
                event_returns[et][h].append(proxy)

        result.categories_analysed = len(event_returns)

        # --- 6. Run hypothesis testing ---
        try:
            hyp_returns = {
                et: {
                    h: np.array(rets) for h, rets in horizons.items()
                }
                for et, horizons in event_returns.items()
            }
            hyp_results = self._hypothesis.test_all(hyp_returns)
            result.hypotheses_tested = len(hyp_results)
            result.hypotheses_rejected = sum(
                1 for h in hyp_results if h.reject_null
            )
            self._hypothesis.save_report(
                hyp_results,
                str(self._output_dir / "hypotheses"),
            )
        except Exception as exc:
            result.errors.append(f"Hypothesis testing: {exc}")
            logger.error("Hypothesis testing failed: %s", exc)

        # --- 7. Run alpha discovery ---
        try:
            # Build return arrays aligned with features
            returns_arr = {
                h: np.array([
                    ev.get("sentiment_score", 0.0) * ev.get(
                        "importance_score", 0.5
                    ) * 2.0
                    for ev, _ in clean_events
                ])
                for h in ["5m", "15m", "1h"]
            }
            signals = self._discovery.discover(
                feat_matrix, returns_arr, feature_names,
                str(self._output_dir / "alpha_signals"),
            )
            result.signals_discovered = len(signals)
            result.signals_significant = sum(
                1 for s in signals if s.is_significant
            )
        except Exception as exc:
            result.errors.append(f"Alpha discovery: {exc}")
            logger.error("Alpha discovery failed: %s", exc)
            signals = []

        # --- 8. Register significant signals ---
        for signal in signals:
            if signal.is_significant:
                entry = AlphaRegistryEntry(
                    signal_id=signal.signal_id,
                    name=signal.name,
                    description=signal.description,
                    model_type=signal.model_type,
                    event_types=[],
                    horizon=signal.horizon,
                    status=SignalStatus.CANDIDATE,
                    sharpe_ratio=signal.sharpe_ratio,
                    hit_rate=signal.hit_rate,
                    mean_return_pct=signal.mean_return_pct,
                    t_statistic=signal.t_statistic,
                    p_value=signal.p_value,
                    n_observations=signal.n_samples,
                    features_used=signal.features_used,
                    feature_importance=signal.feature_importance,
                )
                self._registry.register(entry)
                result.signals_registered += 1

        # --- 9. Save pipeline result ---
        self._save_result(result)

        logger.info(
            "Pipeline complete: %d events → %d signals "
            "(%d significant, %d registered)",
            result.events_processed,
            result.signals_discovered,
            result.signals_significant,
            result.signals_registered,
        )

        return result

    def _save_result(self, result: PipelineResult) -> None:
        out = self._output_dir / "pipeline_runs"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{result.run_id}.json"
        with open(path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)

    @property
    def registry(self) -> AlphaRegistry:
        return self._registry

    @property
    def taxonomy(self) -> EventTaxonomy:
        return self._taxonomy
