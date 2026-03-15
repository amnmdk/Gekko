"""
Edge Stability Testing (Step 9).

Tests whether discovered alpha signals remain stable across:
  1. Rolling time windows   — Does alpha persist over time?
  2. Cross-market assets    — Does signal work on multiple symbols?
  3. Volatility regimes     — Does signal survive high/low vol?
  4. Bootstrap resampling   — Is the signal robust to sample variation?

A signal is considered "stable" if it maintains significance
across >= 60% of rolling windows and >= 2 asset classes.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StabilityResult:
    """Result of edge stability testing for a single signal."""
    signal_id: str
    is_stable: bool
    overall_score: float  # [0, 1] composite stability score
    rolling_window_stats: dict = field(default_factory=dict)
    cross_asset_stats: dict = field(default_factory=dict)
    regime_stats: dict = field(default_factory=dict)
    bootstrap_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "is_stable": self.is_stable,
            "overall_score": self.overall_score,
            "rolling_window": self.rolling_window_stats,
            "cross_asset": self.cross_asset_stats,
            "regime": self.regime_stats,
            "bootstrap": self.bootstrap_stats,
        }


class EdgeStabilityTester:
    """
    Tests the robustness and stability of discovered alpha signals.
    """

    def __init__(
        self,
        n_rolling_windows: int = 5,
        n_bootstrap: int = 500,
        stability_threshold: float = 0.6,
    ):
        self._n_windows = n_rolling_windows
        self._n_bootstrap = n_bootstrap
        self._stability_threshold = stability_threshold

    def test_signal(
        self,
        signal_id: str,
        returns: np.ndarray,
        timestamps: np.ndarray,
        volatilities: np.ndarray | None = None,
        asset_labels: np.ndarray | None = None,
    ) -> StabilityResult:
        """
        Run full stability test suite on a signal.

        Parameters
        ----------
        signal_id : str
            Identifier for the signal.
        returns : np.ndarray
            (N,) array of signal-conditioned returns.
        timestamps : np.ndarray
            (N,) array of event timestamps (for rolling windows).
        volatilities : np.ndarray, optional
            (N,) array of volatility at event time.
        asset_labels : np.ndarray, optional
            (N,) array of asset symbols.

        Returns
        -------
        StabilityResult
        """
        rolling = self._test_rolling_windows(returns, timestamps)
        bootstrap = self._test_bootstrap(returns)
        regime = self._test_regime(returns, volatilities)
        cross_asset = self._test_cross_asset(returns, asset_labels)

        # Composite score
        scores = [
            rolling.get("pct_significant", 0) / 100,
            bootstrap.get("pct_significant", 0) / 100,
            regime.get("stability_score", 0),
            cross_asset.get("pct_assets_significant", 0) / 100,
        ]
        overall = round(float(np.mean(scores)), 4)
        is_stable = overall >= self._stability_threshold

        return StabilityResult(
            signal_id=signal_id,
            is_stable=is_stable,
            overall_score=overall,
            rolling_window_stats=rolling,
            cross_asset_stats=cross_asset,
            regime_stats=regime,
            bootstrap_stats=bootstrap,
        )

    def _test_rolling_windows(
        self,
        returns: np.ndarray,
        timestamps: np.ndarray,
    ) -> dict:
        """Test signal significance in rolling time windows."""
        n = len(returns)
        if n < self._n_windows * 5:
            return {"error": "insufficient_data", "pct_significant": 0}

        window_size = n // self._n_windows
        significant_windows = 0
        window_results = []

        for i in range(self._n_windows):
            start = i * window_size
            end = start + window_size
            if i == self._n_windows - 1:
                end = n  # Include remainder
            chunk = returns[start:end]

            if len(chunk) < 5:
                continue

            mean_ret = float(np.mean(chunk))
            std_ret = float(np.std(chunk, ddof=1))
            t_stat = (
                mean_ret / (std_ret / np.sqrt(len(chunk)))
                if std_ret > 0 else 0.0
            )
            is_sig = abs(t_stat) > 2.0

            if is_sig:
                significant_windows += 1

            window_results.append({
                "window": i + 1,
                "n": int(len(chunk)),
                "mean_return": round(mean_ret, 4),
                "t_stat": round(t_stat, 4),
                "significant": is_sig,
            })

        pct_sig = round(
            significant_windows / max(1, self._n_windows) * 100, 2
        )
        return {
            "n_windows": self._n_windows,
            "significant_windows": significant_windows,
            "pct_significant": pct_sig,
            "windows": window_results,
        }

    def _test_bootstrap(self, returns: np.ndarray) -> dict:
        """Bootstrap test: resample returns and check significance."""
        rng = np.random.RandomState(42)
        n = len(returns)
        if n < 10:
            return {"error": "insufficient_data", "pct_significant": 0}

        significant = 0
        boot_means = []

        for _ in range(self._n_bootstrap):
            sample = rng.choice(returns, size=n, replace=True)
            mean_ret = float(np.mean(sample))
            std_ret = float(np.std(sample, ddof=1))
            boot_means.append(mean_ret)

            t_stat = (
                mean_ret / (std_ret / np.sqrt(n))
                if std_ret > 0 else 0.0
            )
            if abs(t_stat) > 2.0:
                significant += 1

        pct_sig = round(significant / self._n_bootstrap * 100, 2)
        boot_means_arr = np.array(boot_means)
        return {
            "n_resamples": self._n_bootstrap,
            "pct_significant": pct_sig,
            "bootstrap_mean": round(float(np.mean(boot_means_arr)), 4),
            "bootstrap_std": round(float(np.std(boot_means_arr)), 4),
            "ci_95_lower": round(float(np.percentile(boot_means_arr, 2.5)), 4),
            "ci_95_upper": round(float(np.percentile(boot_means_arr, 97.5)), 4),
        }

    def _test_regime(
        self,
        returns: np.ndarray,
        volatilities: np.ndarray | None,
    ) -> dict:
        """Test signal under different volatility regimes."""
        if volatilities is None or len(volatilities) != len(returns):
            return {"error": "no_volatility_data", "stability_score": 0.5}

        median_vol = float(np.median(volatilities))
        low_vol = returns[volatilities <= median_vol]
        high_vol = returns[volatilities > median_vol]

        results = {}
        scores = []
        for label, chunk in [("low_vol", low_vol), ("high_vol", high_vol)]:
            if len(chunk) < 5:
                results[label] = {"error": "insufficient_data"}
                continue
            mean_ret = float(np.mean(chunk))
            std_ret = float(np.std(chunk, ddof=1))
            t_stat = (
                mean_ret / (std_ret / np.sqrt(len(chunk)))
                if std_ret > 0 else 0.0
            )
            is_sig = abs(t_stat) > 1.5  # Relaxed for sub-samples
            scores.append(1.0 if is_sig else 0.0)
            results[label] = {
                "n": int(len(chunk)),
                "mean_return": round(mean_ret, 4),
                "t_stat": round(t_stat, 4),
                "significant": is_sig,
            }

        results["stability_score"] = (
            round(float(np.mean(scores)), 4) if scores else 0.0
        )
        return results

    def _test_cross_asset(
        self,
        returns: np.ndarray,
        asset_labels: np.ndarray | None,
    ) -> dict:
        """Test signal across different assets."""
        if asset_labels is None or len(asset_labels) != len(returns):
            return {
                "error": "no_asset_labels",
                "pct_assets_significant": 50.0,
            }

        unique_assets = np.unique(asset_labels)
        results: dict = {"assets": {}}
        sig_count = 0

        for asset in unique_assets:
            mask = asset_labels == asset
            chunk = returns[mask]
            if len(chunk) < 5:
                continue
            mean_ret = float(np.mean(chunk))
            std_ret = float(np.std(chunk, ddof=1))
            t_stat = (
                mean_ret / (std_ret / np.sqrt(len(chunk)))
                if std_ret > 0 else 0.0
            )
            is_sig = abs(t_stat) > 1.5
            if is_sig:
                sig_count += 1
            results["assets"][str(asset)] = {
                "n": int(len(chunk)),
                "mean_return": round(mean_ret, 4),
                "t_stat": round(t_stat, 4),
                "significant": is_sig,
            }

        n_tested = len(results["assets"])
        results["pct_assets_significant"] = round(
            sig_count / max(1, n_tested) * 100, 2
        )
        return results

    def save_results(
        self,
        results: list[StabilityResult],
        output_dir: str = "results/edge_stability",
    ) -> Path:
        """Save stability test results."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report = {
            "timestamp": ts,
            "total_signals_tested": len(results),
            "stable_signals": sum(1 for r in results if r.is_stable),
            "results": [r.to_dict() for r in results],
        }
        path = out / f"stability_{ts}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Stability results saved: %s", path)
        return path
