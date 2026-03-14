"""
Event Study Analysis

Methodology
-----------
For each event E_i with timestamp t_i:
  1. Align a window of candles: [t_i - pre_candles, t_i + post_candles]
  2. Compute normalised returns at horizons: 5m, 15m, 1h, 4h
  3. Compute volatility expansion ratio: σ_post / σ_pre
  4. Aggregate statistics across all events

Output
------
  - results/event_study_{run_name}_{timestamp}.json  — full metrics
  - results/event_study_{run_name}_{timestamp}.csv   — per-event table
  - results/event_study_{run_name}_{timestamp}.png   — cumulative return chart

Scientific validity note
------------------------
This is a descriptive event study, not a causal inference framework.
Selection bias and look-ahead bias must be considered when interpreting results.
Use walk-forward validation (walkforward.py) for out-of-sample evaluation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class EventStudy:
    """
    Runs an event study over historical events and candles.

    Parameters
    ----------
    candles: pd.DataFrame
        OHLCV candles with datetime index (UTC). Must include 'close', 'volume'.
    pre_candles: int
        Number of candles before event to include in window.
    post_candles: int
        Number of candles after event to include in analysis.
    timeframe_minutes: int
        Duration per candle in minutes.
    """

    HORIZONS = [1, 3, 12, 48]  # Candles at 5m = 5m, 15m, 1h, 4h

    def __init__(
        self,
        candles: pd.DataFrame,
        pre_candles: int = 12,
        post_candles: int = 48,
        timeframe_minutes: int = 5,
    ):
        self._candles = candles.sort_index()
        self._pre = pre_candles
        self._post = post_candles
        self._tf_min = timeframe_minutes

    def run(
        self,
        events: list[dict],
        output_dir: str = "results",
        run_name: str = "study",
    ) -> dict:
        """
        Run event study over *events*.

        Parameters
        ----------
        events: list[dict]
            Each dict must have:
              - 'event_id': str
              - 'published_at': str ISO datetime
              - 'headline': str
              - 'domain': str
              - 'sentiment_score': float  (optional)
        output_dir: str
            Directory to save outputs.
        run_name: str
            Label for output files.

        Returns
        -------
        dict with aggregated statistics and per-event results.
        """
        results_dir = Path(output_dir)
        results_dir.mkdir(parents=True, exist_ok=True)

        event_windows: list[dict] = []
        skipped = 0

        for ev in events:
            window = self._compute_window(ev)
            if window is None:
                skipped += 1
                continue
            event_windows.append(window)

        logger.info(
            "Event study: %d events processed, %d skipped (insufficient candle data)",
            len(event_windows), skipped,
        )

        if not event_windows:
            logger.warning("No valid event windows — event study aborted.")
            return {"error": "no_valid_windows", "skipped": skipped}

        # --- Aggregate statistics ---
        agg = self._aggregate(event_windows)

        # --- Build report ---
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = f"event_study_{run_name}_{timestamp}"

        report = {
            "run_name": run_name,
            "timestamp": timestamp,
            "n_events": len(event_windows),
            "n_skipped": skipped,
            "timeframe_minutes": self._tf_min,
            "pre_candles": self._pre,
            "post_candles": self._post,
            "aggregate": agg,
            "per_event": event_windows,
        }

        # JSON output
        json_path = results_dir / f"{base_name}.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Event study JSON saved: %s", json_path)

        # CSV output
        df = pd.DataFrame(event_windows)
        csv_path = results_dir / f"{base_name}.csv"
        df.to_csv(csv_path, index=False)
        logger.info("Event study CSV saved: %s", csv_path)

        # Plot
        plot_path = results_dir / f"{base_name}.png"
        self._plot_cumulative_returns(event_windows, plot_path, run_name)

        return report

    # ------------------------------------------------------------------
    # Window computation
    # ------------------------------------------------------------------

    def _compute_window(self, event: dict) -> Optional[dict]:
        """
        Compute candle-aligned returns for a single event.
        Returns None if insufficient candle data.
        """
        try:
            ts = pd.Timestamp(event["published_at"]).tz_localize("UTC") \
                if pd.Timestamp(event["published_at"]).tzinfo is None \
                else pd.Timestamp(event["published_at"]).tz_convert("UTC")
        except Exception:
            return None

        # Find nearest candle index
        idx = self._candles.index.searchsorted(ts)
        if idx >= len(self._candles):
            idx = len(self._candles) - 1

        pre_start = idx - self._pre
        post_end = idx + self._post

        if pre_start < 1 or post_end >= len(self._candles):
            return None  # Insufficient data

        pre_window = self._candles.iloc[pre_start:idx]
        post_window = self._candles.iloc[idx:post_end + 1]

        event_price = float(self._candles["close"].iloc[idx])
        if event_price <= 0:
            return None

        # Compute returns at horizons
        returns = {}
        for h in self.HORIZONS:
            if h < len(post_window):
                future_price = float(post_window["close"].iloc[h])
                returns[f"ret_{h}c"] = round((future_price / event_price - 1) * 100, 4)
                minutes = h * self._tf_min
                returns[f"ret_{minutes}m"] = returns[f"ret_{h}c"]
            else:
                returns[f"ret_{h}c"] = None
                minutes = h * self._tf_min
                returns[f"ret_{minutes}m"] = None

        # Volatility expansion
        pre_vol = float(pre_window["close"].pct_change().std()) if len(pre_window) > 1 else 0.0
        post_vol = float(post_window["close"].pct_change().std()) if len(post_window) > 1 else 0.0
        vol_expansion = (post_vol / pre_vol) if pre_vol > 0 else 1.0

        # Normalised return path (cumulative from event)
        path = ((post_window["close"] / event_price) - 1).tolist()

        result = {
            "event_id": event.get("event_id", ""),
            "headline": event.get("headline", "")[:100],
            "domain": event.get("domain", ""),
            "published_at": str(ts),
            "event_price": round(event_price, 4),
            "sentiment_score": event.get("sentiment_score", 0.0),
            "vol_expansion_ratio": round(vol_expansion, 4),
            "return_path": [round(r, 6) for r in path],
            **returns,
        }
        return result

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, windows: list[dict]) -> dict:
        df = pd.DataFrame(windows)
        agg = {}
        for h in self.HORIZONS:
            col = f"ret_{h}c"
            if col not in df.columns:
                continue
            series = df[col].dropna()
            if len(series) == 0:
                continue
            minutes = h * self._tf_min
            agg[f"ret_{minutes}m"] = {
                "mean": round(float(series.mean()), 4),
                "median": round(float(series.median()), 4),
                "std": round(float(series.std()), 4),
                "t_stat": round(
                    float(series.mean() / (series.std() / np.sqrt(len(series))))
                    if series.std() > 0 else 0.0, 4
                ),
                "pct_positive": round(float((series > 0).mean() * 100), 2),
                "n": int(len(series)),
            }

        # Volatility expansion stats
        if "vol_expansion_ratio" in df.columns:
            ve = df["vol_expansion_ratio"].dropna()
            agg["volatility_expansion"] = {
                "mean": round(float(ve.mean()), 4),
                "median": round(float(ve.median()), 4),
                "pct_above_1": round(float((ve > 1.0).mean() * 100), 2),
            }

        # By domain
        if "domain" in df.columns:
            agg["by_domain"] = {}
            for domain in df["domain"].unique():
                sub = df[df["domain"] == domain]
                col = "ret_1c"
                if col in sub.columns:
                    s = sub[col].dropna()
                    agg["by_domain"][domain] = {
                        "n": int(len(s)),
                        "mean_5m_ret": round(float(s.mean()), 4) if len(s) > 0 else 0.0,
                    }

        return agg

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------

    def _plot_cumulative_returns(
        self, windows: list[dict], output_path: Path, run_name: str
    ) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available — skipping plot")
            return

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"Event Study: {run_name}", fontsize=13, fontweight="bold")

        # Left: Average cumulative return path
        ax1 = axes[0]
        paths = [w["return_path"] for w in windows if w.get("return_path")]
        if paths:
            max_len = min(self._post, min(len(p) for p in paths))
            paths_arr = np.array([p[:max_len] for p in paths]) * 100
            mean_path = np.mean(paths_arr, axis=0)
            std_path = np.std(paths_arr, axis=0)
            x = np.arange(max_len) * self._tf_min

            ax1.plot(x, mean_path, color="steelblue", linewidth=2, label="Mean return")
            ax1.fill_between(
                x,
                mean_path - std_path,
                mean_path + std_path,
                alpha=0.2, color="steelblue", label="±1σ"
            )
            ax1.axhline(0, color="black", linewidth=0.8, linestyle="--")
            ax1.axvline(0, color="red", linewidth=1.0, linestyle="--", label="Event")
            ax1.set_xlabel("Minutes after event")
            ax1.set_ylabel("Cumulative return (%)")
            ax1.set_title("Average Price Path After Event")
            ax1.legend(fontsize=8)
            ax1.grid(True, alpha=0.3)

        # Right: Distribution of 1h returns
        ax2 = axes[1]
        col_1h = "ret_60m"
        ret_1h = [w.get(col_1h) for w in windows if w.get(col_1h) is not None]
        if ret_1h:
            ax2.hist(ret_1h, bins=20, color="coral", edgecolor="white", alpha=0.8)
            ax2.axvline(0, color="black", linewidth=0.8, linestyle="--")
            ax2.axvline(
                float(np.mean(ret_1h)), color="darkred", linewidth=1.5,
                linestyle="-", label=f"Mean={np.mean(ret_1h):.2f}%"
            )
            ax2.set_xlabel("1-hour return (%)")
            ax2.set_ylabel("Count")
            ax2.set_title("Distribution of 1h Post-Event Returns")
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info("Event study plot saved: %s", output_path)
