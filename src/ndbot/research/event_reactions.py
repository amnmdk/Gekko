"""
Event Reaction Analysis (Step 3).

Extends the base EventStudy engine with per-category reaction analysis:
  - Groups events by taxonomy event_type
  - Computes returns at 5m, 15m, 1h, 4h, 1d horizons
  - Produces per-category statistical summaries
  - Outputs structured results to results/event_reactions/

This module answers: "How does the market ACTUALLY react to each event type?"
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .event_study import EventStudy
from .event_taxonomy import EventTaxonomy

logger = logging.getLogger(__name__)


class EventReactionAnalyser:
    """
    Analyses market reactions to events grouped by taxonomy category.

    Produces per-category statistical profiles at multiple horizons,
    enabling researchers to identify which event types generate
    tradeable reactions.
    """

    # Extended horizons: 5m, 15m, 1h, 4h, 1d (at 5-min candles)
    HORIZONS_CANDLES = [1, 3, 12, 48, 288]
    HORIZON_LABELS = ["5m", "15m", "1h", "4h", "1d"]

    def __init__(
        self,
        candles: pd.DataFrame,
        taxonomy: Optional[EventTaxonomy] = None,
        timeframe_minutes: int = 5,
    ):
        self._candles = candles.sort_index()
        self._taxonomy = taxonomy or EventTaxonomy()
        self._tf_min = timeframe_minutes
        self._study = EventStudy(
            candles, pre_candles=12, post_candles=300,
            timeframe_minutes=timeframe_minutes,
        )

    def analyse(
        self,
        events: list[dict],
        output_dir: str = "results/event_reactions",
    ) -> dict:
        """
        Run per-category reaction analysis.

        Parameters
        ----------
        events : list[dict]
            Each dict must have 'event_id', 'published_at', 'headline',
            'domain', and optionally 'event_type'.
        output_dir : str
            Directory for output files.

        Returns
        -------
        dict with per-category reaction profiles.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Classify events if not already classified
        for ev in events:
            if "event_type" not in ev or ev["event_type"] == "UNKNOWN":
                best = self._taxonomy.classify_best(
                    ev.get("headline", "")
                )
                if best:
                    ev["event_type"] = best[0]
                else:
                    ev["event_type"] = "UNKNOWN"

        # Group by event_type
        groups: dict[str, list[dict]] = {}
        for ev in events:
            et = ev.get("event_type", "UNKNOWN")
            groups.setdefault(et, []).append(ev)

        # Analyse each group
        results: dict[str, dict] = {}
        for event_type, group_events in groups.items():
            profile = self._analyse_group(event_type, group_events)
            if profile:
                results[event_type] = profile

        # Build summary report
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_events": len(events),
            "categories_analysed": len(results),
            "categories": results,
            "ranking": self._rank_categories(results),
        }

        # Save
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = out / f"reactions_{ts}.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Event reactions saved: %s", json_path)

        return report

    def _analyse_group(
        self, event_type: str, events: list[dict]
    ) -> Optional[dict]:
        """Compute reaction statistics for a single event type."""
        if len(events) < 2:
            return None

        windows = []
        for ev in events:
            w = self._study._compute_window(ev)
            if w is not None:
                windows.append(w)

        if not windows:
            return None

        df = pd.DataFrame(windows)

        # Get taxonomy metadata
        et_info = self._taxonomy.get(event_type)

        profile: dict = {
            "event_type": event_type,
            "label": et_info.label if et_info else event_type,
            "expected_impact": (
                et_info.expected_impact.value if et_info else "UNKNOWN"
            ),
            "n_events": len(windows),
            "horizons": {},
        }

        # Compute stats at each horizon
        for h_candles, h_label in zip(
            self.HORIZONS_CANDLES, self.HORIZON_LABELS
        ):
            col = f"ret_{h_candles}c"
            if col not in df.columns:
                continue
            series = df[col].dropna()
            if len(series) < 2:
                continue

            mean_ret = float(series.mean())
            std_ret = float(series.std())
            t_stat = (
                mean_ret / (std_ret / np.sqrt(len(series)))
                if std_ret > 0 else 0.0
            )
            # Two-tailed p-value approximation
            from scipy import stats as sp_stats
            try:
                p_value = float(
                    2 * (1 - sp_stats.t.cdf(abs(t_stat), len(series) - 1))
                )
            except Exception:
                p_value = 1.0

            profile["horizons"][h_label] = {
                "mean_return_pct": round(mean_ret, 4),
                "median_return_pct": round(float(series.median()), 4),
                "std_pct": round(std_ret, 4),
                "t_statistic": round(t_stat, 4),
                "p_value": round(p_value, 6),
                "significant_5pct": p_value < 0.05,
                "pct_positive": round(
                    float((series > 0).mean() * 100), 2
                ),
                "sharpe_ratio": round(
                    mean_ret / std_ret if std_ret > 0 else 0.0, 4
                ),
                "n": int(len(series)),
            }

        # Volatility expansion
        if "vol_expansion_ratio" in df.columns:
            ve = df["vol_expansion_ratio"].dropna()
            if len(ve) > 0:
                profile["vol_expansion"] = {
                    "mean": round(float(ve.mean()), 4),
                    "median": round(float(ve.median()), 4),
                    "pct_above_1": round(
                        float((ve > 1.0).mean() * 100), 2
                    ),
                }

        return profile

    def _rank_categories(self, results: dict) -> list[dict]:
        """
        Rank event types by tradeable signal strength.
        Uses 1h horizon t-statistic as primary ranking metric.
        """
        rankings = []
        for code, profile in results.items():
            h1 = profile.get("horizons", {}).get("1h", {})
            rankings.append({
                "event_type": code,
                "label": profile.get("label", code),
                "n_events": profile.get("n_events", 0),
                "mean_1h_return": h1.get("mean_return_pct", 0.0),
                "t_stat_1h": h1.get("t_statistic", 0.0),
                "p_value_1h": h1.get("p_value", 1.0),
                "significant": h1.get("significant_5pct", False),
            })
        rankings.sort(key=lambda x: abs(x["t_stat_1h"]), reverse=True)
        return rankings
