"""
Hypothesis Testing Engine (Step 7).

Formalises alpha discovery into testable hypotheses with
rigorous statistical evaluation:

  - H0: Event type X has no effect on asset returns at horizon H
  - H1: Event type X generates mean return != 0 at horizon H

Tests applied:
  1. Two-sided t-test on post-event returns
  2. Bootstrap confidence intervals (1000 resamples)
  3. Multiple testing correction (Bonferroni and BH-FDR)
  4. Effect size (Cohen's d)

Outputs structured hypothesis reports for the alpha registry.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HypothesisResult:
    """Result of testing a single hypothesis."""
    hypothesis_id: str
    description: str
    event_type: str
    horizon: str
    n_observations: int
    mean_return_pct: float
    std_return_pct: float
    t_statistic: float
    p_value: float
    p_value_adjusted: float  # After multiple testing correction
    ci_lower: float  # 95% CI lower bound
    ci_upper: float  # 95% CI upper bound
    cohens_d: float  # Effect size
    hit_rate: float
    reject_null: bool  # At 5% after correction
    practical_significance: bool  # |d| > 0.2 and Sharpe > 0.3

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "description": self.description,
            "event_type": self.event_type,
            "horizon": self.horizon,
            "n_observations": self.n_observations,
            "mean_return_pct": self.mean_return_pct,
            "std_return_pct": self.std_return_pct,
            "t_statistic": self.t_statistic,
            "p_value": self.p_value,
            "p_value_adjusted": self.p_value_adjusted,
            "ci_lower": self.ci_lower,
            "ci_upper": self.ci_upper,
            "cohens_d": self.cohens_d,
            "hit_rate": self.hit_rate,
            "reject_null": self.reject_null,
            "practical_significance": self.practical_significance,
        }


class HypothesisEngine:
    """
    Runs formal hypothesis tests on event-return relationships.

    Usage:
        engine = HypothesisEngine()
        results = engine.test_all(event_returns)
        engine.save_report(results, "results/hypotheses")
    """

    def __init__(
        self,
        alpha: float = 0.05,
        n_bootstrap: int = 1000,
        min_samples: int = 10,
        correction: str = "bh",  # "bonferroni" or "bh" (Benjamini-Hochberg)
    ):
        self._alpha = alpha
        self._n_bootstrap = n_bootstrap
        self._min_samples = min_samples
        self._correction = correction

    def test_all(
        self,
        event_returns: dict[str, dict[str, np.ndarray]],
    ) -> list[HypothesisResult]:
        """
        Test all event_type × horizon combinations.

        Parameters
        ----------
        event_returns : dict[str, dict[str, np.ndarray]]
            event_type -> {horizon -> returns_array}

        Returns
        -------
        list[HypothesisResult]
        """
        raw_results: list[HypothesisResult] = []

        for event_type, horizons in event_returns.items():
            for horizon, returns in horizons.items():
                if len(returns) < self._min_samples:
                    continue
                result = self._test_single(
                    event_type, horizon, returns,
                )
                raw_results.append(result)

        # Apply multiple testing correction
        if raw_results:
            self._apply_correction(raw_results)

        # Sort by adjusted p-value
        raw_results.sort(key=lambda r: r.p_value_adjusted)
        return raw_results

    def _test_single(
        self,
        event_type: str,
        horizon: str,
        returns: np.ndarray,
    ) -> HypothesisResult:
        """Test a single event_type × horizon hypothesis."""
        n = len(returns)
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))

        # t-test
        se = std_ret / math.sqrt(n) if n > 1 else 1.0
        t_stat = mean_ret / se if se > 0 else 0.0
        p_value = self._t_to_p(t_stat, n)

        # Bootstrap 95% CI
        ci_lower, ci_upper = self._bootstrap_ci(returns)

        # Effect size (Cohen's d)
        cohens_d = mean_ret / std_ret if std_ret > 0 else 0.0

        # Hit rate
        hit_rate = float(np.mean(returns > 0))

        # Practical significance: meaningful effect + reasonable Sharpe
        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
        practical = abs(cohens_d) > 0.2 and abs(sharpe) > 0.3

        return HypothesisResult(
            hypothesis_id=f"H_{event_type}_{horizon}",
            description=(
                f"H0: {event_type} has no effect on {horizon} returns. "
                f"H1: Mean return != 0."
            ),
            event_type=event_type,
            horizon=horizon,
            n_observations=n,
            mean_return_pct=round(mean_ret, 4),
            std_return_pct=round(std_ret, 4),
            t_statistic=round(t_stat, 4),
            p_value=round(p_value, 6),
            p_value_adjusted=round(p_value, 6),  # Updated later
            ci_lower=round(ci_lower, 4),
            ci_upper=round(ci_upper, 4),
            cohens_d=round(cohens_d, 4),
            hit_rate=round(hit_rate, 4),
            reject_null=False,  # Updated after correction
            practical_significance=practical,
        )

    def _bootstrap_ci(
        self, returns: np.ndarray, confidence: float = 0.95,
    ) -> tuple[float, float]:
        """Compute bootstrap confidence interval for the mean."""
        rng = np.random.RandomState(42)
        n = len(returns)
        boot_means = []
        for _ in range(self._n_bootstrap):
            sample = rng.choice(returns, size=n, replace=True)
            boot_means.append(float(np.mean(sample)))
        boot_means.sort()
        alpha_half = (1 - confidence) / 2
        lo = int(alpha_half * self._n_bootstrap)
        hi = int((1 - alpha_half) * self._n_bootstrap) - 1
        return boot_means[lo], boot_means[hi]

    def _apply_correction(
        self, results: list[HypothesisResult]
    ) -> None:
        """Apply multiple testing correction in-place."""
        p_values = [r.p_value for r in results]
        m = len(p_values)

        if self._correction == "bonferroni":
            for r in results:
                r.p_value_adjusted = round(
                    min(1.0, r.p_value * m), 6
                )
                r.reject_null = r.p_value_adjusted < self._alpha
        else:
            # Benjamini-Hochberg FDR
            sorted_indices = np.argsort(p_values)
            for rank, idx in enumerate(sorted_indices, 1):
                adjusted = min(
                    1.0, p_values[idx] * m / rank
                )
                results[idx].p_value_adjusted = round(adjusted, 6)

            # Enforce monotonicity (step-up)
            sorted_by_p = sorted(
                range(m), key=lambda i: results[i].p_value,
            )
            min_so_far = 1.0
            for i in reversed(sorted_by_p):
                min_so_far = min(
                    min_so_far, results[i].p_value_adjusted,
                )
                results[i].p_value_adjusted = round(min_so_far, 6)
                results[i].reject_null = min_so_far < self._alpha

    def save_report(
        self,
        results: list[HypothesisResult],
        output_dir: str = "results/hypotheses",
    ) -> Path:
        """Save hypothesis test report."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report = {
            "timestamp": ts,
            "alpha": self._alpha,
            "correction_method": self._correction,
            "n_bootstrap": self._n_bootstrap,
            "total_hypotheses": len(results),
            "rejected_null": sum(1 for r in results if r.reject_null),
            "practically_significant": sum(
                1 for r in results if r.practical_significance
            ),
            "hypotheses": [r.to_dict() for r in results],
        }

        path = out / f"hypothesis_report_{ts}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Hypothesis report saved: %s", path)
        return path

    @staticmethod
    def _t_to_p(t_stat: float, n: int) -> float:
        try:
            from scipy import stats as sp_stats
            return float(
                2 * (1 - sp_stats.t.cdf(abs(t_stat), max(1, n - 1)))
            )
        except ImportError:
            return 0.05 if abs(t_stat) > 2.0 else 0.5
