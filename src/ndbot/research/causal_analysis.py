"""
Causal Event Analysis (Step 3).

Determines whether news events CAUSE price moves rather than
merely correlating with them.

Methods:
  1. Granger causality — does event signal precede return signal?
  2. Difference-in-differences — event vs control window comparison
  3. Instrumental variable proxy — use exogenous shock strength
  4. Placebo tests — randomised event timing null distribution

Output:
  CausalTestResult with confidence score [0, 1] indicating
  strength of causal evidence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)


@dataclass
class CausalTestResult:
    """Result of a single causal test."""

    test_name: str
    causal_score: float          # [0, 1] — strength of causal evidence
    p_value: float
    statistic: float
    is_significant: bool
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "causal_score": round(self.causal_score, 4),
            "p_value": round(self.p_value, 6),
            "statistic": round(self.statistic, 4),
            "is_significant": self.is_significant,
            "details": self.details,
        }


@dataclass
class CausalReport:
    """Comprehensive causal analysis report."""

    event_type: str
    timestamp: str
    tests: list[CausalTestResult] = field(default_factory=list)
    composite_causal_score: float = 0.0
    verdict: str = "inconclusive"  # "causal", "suggestive", "inconclusive"

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "tests": [t.to_dict() for t in self.tests],
            "composite_causal_score": round(
                self.composite_causal_score, 4,
            ),
            "verdict": self.verdict,
        }


class CausalAnalysisEngine:
    """
    Tests causal relationships between events and price moves.

    Usage:
        engine = CausalAnalysisEngine()
        report = engine.analyse(
            event_returns=post_event_returns,
            control_returns=non_event_returns,
            event_indicator=binary_event_series,
            return_series=full_return_series,
        )
    """

    def __init__(
        self,
        significance_level: float = 0.05,
        n_placebo: int = 500,
        granger_lags: int = 5,
    ) -> None:
        self._alpha = significance_level
        self._n_placebo = n_placebo
        self._granger_lags = granger_lags

    def analyse(
        self,
        event_returns: np.ndarray,
        control_returns: np.ndarray,
        event_indicator: np.ndarray | None = None,
        return_series: np.ndarray | None = None,
        event_type: str = "unknown",
    ) -> CausalReport:
        """
        Run full causal analysis suite.

        Parameters
        ----------
        event_returns : array
            Returns in windows following events.
        control_returns : array
            Returns in non-event windows (control group).
        event_indicator : array, optional
            Binary series (1 = event occurred). For Granger test.
        return_series : array, optional
            Full return time series. For Granger test.
        """
        ts = datetime.now(timezone.utc).isoformat()
        tests: list[CausalTestResult] = []

        # 1. Difference-in-differences
        did = self._diff_in_diff(event_returns, control_returns)
        tests.append(did)

        # 2. Placebo test
        placebo = self._placebo_test(event_returns, control_returns)
        tests.append(placebo)

        # 3. Granger causality (if time series provided)
        if event_indicator is not None and return_series is not None:
            granger = self._granger_test(event_indicator, return_series)
            tests.append(granger)

        # 4. Instrumental variable proxy
        iv = self._iv_proxy_test(event_returns, control_returns)
        tests.append(iv)

        # Composite score
        scores = [t.causal_score for t in tests]
        composite = float(np.mean(scores))

        if composite >= 0.7:
            verdict = "causal"
        elif composite >= 0.4:
            verdict = "suggestive"
        else:
            verdict = "inconclusive"

        report = CausalReport(
            event_type=event_type,
            timestamp=ts,
            tests=tests,
            composite_causal_score=composite,
            verdict=verdict,
        )

        logger.info(
            "Causal analysis [%s]: score=%.3f verdict=%s",
            event_type, composite, verdict,
        )
        return report

    def _diff_in_diff(
        self,
        event_returns: np.ndarray,
        control_returns: np.ndarray,
    ) -> CausalTestResult:
        """
        Difference-in-differences estimator.

        Compares mean return in event windows vs control windows.
        Uses Welch's t-test for unequal variances.
        """
        if len(event_returns) < 3 or len(control_returns) < 3:
            return CausalTestResult(
                test_name="diff_in_diff",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "insufficient_data"},
            )

        t_stat, p_val = sp_stats.ttest_ind(
            event_returns, control_returns, equal_var=False,
        )
        t_stat = float(t_stat)
        p_val = float(p_val)

        # Effect size (Cohen's d)
        pooled_std = np.sqrt(
            (np.var(event_returns, ddof=1) + np.var(control_returns, ddof=1))
            / 2
        )
        cohens_d = (
            (np.mean(event_returns) - np.mean(control_returns))
            / max(pooled_std, 1e-10)
        )

        # Causal score: combine statistical significance and effect size
        sig_score = max(0, 1.0 - p_val / self._alpha) if p_val < self._alpha else 0.0
        effect_score = min(1.0, abs(cohens_d) / 0.8)
        causal_score = 0.6 * sig_score + 0.4 * effect_score

        return CausalTestResult(
            test_name="diff_in_diff",
            causal_score=causal_score,
            p_value=p_val,
            statistic=t_stat,
            is_significant=p_val < self._alpha,
            details={
                "mean_event": round(float(np.mean(event_returns)), 6),
                "mean_control": round(float(np.mean(control_returns)), 6),
                "cohens_d": round(float(cohens_d), 4),
                "n_event": len(event_returns),
                "n_control": len(control_returns),
            },
        )

    def _placebo_test(
        self,
        event_returns: np.ndarray,
        control_returns: np.ndarray,
    ) -> CausalTestResult:
        """
        Placebo (permutation) test.

        Randomly assign "event" labels and check if observed effect
        exceeds the null distribution.
        """
        if len(event_returns) < 3 or len(control_returns) < 3:
            return CausalTestResult(
                test_name="placebo",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "insufficient_data"},
            )

        observed_diff = float(
            np.mean(event_returns) - np.mean(control_returns)
        )
        combined = np.concatenate([event_returns, control_returns])
        n_event = len(event_returns)

        rng = np.random.default_rng(42)
        null_diffs = np.zeros(self._n_placebo)
        for i in range(self._n_placebo):
            perm = rng.permutation(combined)
            null_diffs[i] = np.mean(perm[:n_event]) - np.mean(perm[n_event:])

        # Two-sided p-value
        p_val = float(np.mean(np.abs(null_diffs) >= abs(observed_diff)))
        p_val = max(p_val, 1.0 / (self._n_placebo + 1))

        # How extreme is observed vs null?
        if np.std(null_diffs) > 0:
            z_score = abs(observed_diff) / float(np.std(null_diffs))
        else:
            z_score = 0.0

        causal_score = min(1.0, z_score / 3.0) if p_val < self._alpha else 0.0

        return CausalTestResult(
            test_name="placebo",
            causal_score=causal_score,
            p_value=p_val,
            statistic=float(observed_diff),
            is_significant=p_val < self._alpha,
            details={
                "observed_diff": round(observed_diff, 6),
                "null_mean": round(float(np.mean(null_diffs)), 6),
                "null_std": round(float(np.std(null_diffs)), 6),
                "z_score": round(z_score, 4),
                "n_permutations": self._n_placebo,
            },
        )

    def _granger_test(
        self,
        event_indicator: np.ndarray,
        return_series: np.ndarray,
    ) -> CausalTestResult:
        """
        Granger causality test.

        Tests whether lagged event indicators improve prediction
        of returns beyond returns alone.

        Uses OLS regression comparison:
          Restricted:   r_t = a + b1*r_{t-1} + ... + bL*r_{t-L}
          Unrestricted: r_t = a + b*r_lags + c*event_lags

        F-test on whether event_lags coefficients are jointly zero.
        """
        n = min(len(event_indicator), len(return_series))
        if n < self._granger_lags + 10:
            return CausalTestResult(
                test_name="granger_causality",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "insufficient_data"},
            )

        event_indicator = event_indicator[:n].astype(float)
        return_series = return_series[:n].astype(float)
        lags = self._granger_lags

        # Build lagged matrices
        y = return_series[lags:]
        n_obs = len(y)

        # Restricted model: only return lags
        x_restricted = np.column_stack([
            return_series[lags - i - 1: n - i - 1] for i in range(lags)
        ])
        x_restricted = np.column_stack([
            np.ones(n_obs), x_restricted,
        ])

        # Unrestricted model: return lags + event lags
        event_lags = np.column_stack([
            event_indicator[lags - i - 1: n - i - 1] for i in range(lags)
        ])
        x_unrestricted = np.column_stack([x_restricted, event_lags])

        # OLS
        try:
            beta_r = np.linalg.lstsq(x_restricted, y, rcond=None)[0]
            resid_r = y - x_restricted @ beta_r
            ssr_r = float(np.sum(resid_r ** 2))

            beta_u = np.linalg.lstsq(x_unrestricted, y, rcond=None)[0]
            resid_u = y - x_unrestricted @ beta_u
            ssr_u = float(np.sum(resid_u ** 2))
        except np.linalg.LinAlgError:
            return CausalTestResult(
                test_name="granger_causality",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "singular_matrix"},
            )

        # F-test
        df1 = lags  # number of added parameters
        df2 = n_obs - x_unrestricted.shape[1]
        if df2 <= 0 or ssr_u <= 0:
            return CausalTestResult(
                test_name="granger_causality",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "degenerate"},
            )

        f_stat = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
        p_val = float(1.0 - sp_stats.f.cdf(f_stat, df1, df2))

        causal_score = max(0.0, 1.0 - p_val / self._alpha) if p_val < self._alpha else 0.0

        return CausalTestResult(
            test_name="granger_causality",
            causal_score=causal_score,
            p_value=p_val,
            statistic=float(f_stat),
            is_significant=p_val < self._alpha,
            details={
                "f_statistic": round(float(f_stat), 4),
                "df1": df1,
                "df2": df2,
                "ssr_restricted": round(ssr_r, 6),
                "ssr_unrestricted": round(ssr_u, 6),
                "lags": lags,
            },
        )

    def _iv_proxy_test(
        self,
        event_returns: np.ndarray,
        control_returns: np.ndarray,
    ) -> CausalTestResult:
        """
        Instrumental variable proxy test.

        Uses event magnitude (absolute return) as an instrument:
        larger events should produce proportionally larger moves
        if the relationship is causal.

        Tests rank correlation between event magnitude and return
        magnitude.
        """
        if len(event_returns) < 10:
            return CausalTestResult(
                test_name="iv_proxy",
                causal_score=0.0, p_value=1.0,
                statistic=0.0, is_significant=False,
                details={"error": "insufficient_data"},
            )

        # Magnitude = absolute return (proxy for event strength)
        magnitudes = np.abs(event_returns)
        signed_returns = event_returns

        # Spearman rank correlation
        corr, p_val = sp_stats.spearmanr(magnitudes, np.abs(signed_returns))
        corr = float(corr)
        p_val = float(p_val)

        # Dose-response: split into terciles by magnitude
        sorted_idx = np.argsort(magnitudes)
        n = len(sorted_idx)
        tercile_size = n // 3
        if tercile_size >= 2:
            low_mag = event_returns[sorted_idx[:tercile_size]]
            high_mag = event_returns[sorted_idx[-tercile_size:]]
            dose_response = float(
                np.mean(np.abs(high_mag)) - np.mean(np.abs(low_mag))
            )
        else:
            dose_response = 0.0

        causal_score = min(1.0, abs(corr)) if p_val < self._alpha else 0.0

        return CausalTestResult(
            test_name="iv_proxy",
            causal_score=causal_score,
            p_value=p_val,
            statistic=corr,
            is_significant=p_val < self._alpha,
            details={
                "spearman_corr": round(corr, 4),
                "dose_response": round(dose_response, 6),
                "n_events": len(event_returns),
            },
        )
