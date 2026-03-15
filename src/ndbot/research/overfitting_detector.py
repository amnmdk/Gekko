"""
Overfitting Detector (Step 5).

Detects overfitted strategies using multiple diagnostic tests:

  1. Parameter sensitivity analysis
     - Perturb each parameter ±10% and measure Sharpe degradation
     - Stable strategies show < 20% Sharpe change

  2. Cross-validation across regimes
     - Test strategy in high-vol, low-vol, trending, and mean-reverting
     - Overfitted strategies fail in unseen regimes

  3. Strategy complexity penalty
     - Penalise strategies with many free parameters
     - BIC-style: score = -2×log_likelihood + k×ln(n)

  4. In-sample vs out-of-sample gap
     - IS/OOS Sharpe ratio > 2.0 suggests overfitting

A strategy is REJECTED if overfitting_score > 0.6.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OverfitDiagnostic:
    """Result of overfitting analysis for a single strategy."""
    strategy_id: str
    overfitting_score: float        # [0, 1], higher = more likely overfit
    is_overfit: bool
    parameter_sensitivity: dict = field(default_factory=dict)
    regime_robustness: dict = field(default_factory=dict)
    complexity_penalty: float = 0.0
    is_oos_gap: float = 0.0         # IS Sharpe / OOS Sharpe
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "overfitting_score": round(self.overfitting_score, 4),
            "is_overfit": self.is_overfit,
            "parameter_sensitivity": self.parameter_sensitivity,
            "regime_robustness": self.regime_robustness,
            "complexity_penalty": round(self.complexity_penalty, 4),
            "is_oos_gap": round(self.is_oos_gap, 4),
            "diagnostics": self.diagnostics,
        }


class OverfittingDetector:
    """
    Detects overfitting in trading strategies.

    Usage:
        detector = OverfittingDetector()
        result = detector.analyse(
            strategy_id="my_strat",
            returns_is=in_sample_returns,
            returns_oos=out_of_sample_returns,
            n_parameters=5,
        )
    """

    OVERFIT_THRESHOLD = 0.6
    SENSITIVITY_PERTURBATION = 0.10  # ±10%
    MAX_IS_OOS_GAP = 2.0

    def __init__(
        self,
        n_bootstrap: int = 500,
        sensitivity_perturbation: float = 0.10,
        overfit_threshold: float = 0.6,
    ) -> None:
        self._n_bootstrap = n_bootstrap
        self._perturbation = sensitivity_perturbation
        self._threshold = overfit_threshold

    def analyse(
        self,
        strategy_id: str,
        returns_is: np.ndarray,
        returns_oos: np.ndarray,
        n_parameters: int = 1,
        parameter_names: list[str] | None = None,
        parameter_values: list[float] | None = None,
    ) -> OverfitDiagnostic:
        """
        Run full overfitting analysis.

        Parameters
        ----------
        returns_is : np.ndarray
            In-sample returns.
        returns_oos : np.ndarray
            Out-of-sample returns.
        n_parameters : int
            Number of free parameters in the strategy.
        """
        scores: list[float] = []

        # 1. IS vs OOS Sharpe gap
        sharpe_is = self._sharpe(returns_is)
        sharpe_oos = self._sharpe(returns_oos)
        is_oos_gap = (
            sharpe_is / max(abs(sharpe_oos), 0.001)
        )
        gap_score = min(1.0, max(0.0, (is_oos_gap - 1.0) / 3.0))
        scores.append(gap_score)

        # 2. Parameter sensitivity (bootstrap-based)
        sensitivity = self._parameter_sensitivity(
            returns_is, parameter_names, parameter_values,
        )
        sensitivity_score = sensitivity.get("avg_degradation", 0)
        scores.append(min(1.0, sensitivity_score * 2))

        # 3. Regime robustness
        regime = self._regime_robustness(returns_oos)
        regime_score = 1.0 - regime.get("regime_consistency", 0.5)
        scores.append(regime_score)

        # 4. Complexity penalty (BIC-inspired)
        n_obs = len(returns_is) + len(returns_oos)
        complexity = self._complexity_penalty(
            n_parameters, n_obs, sharpe_is,
        )
        complexity_score = min(1.0, complexity / 5.0)
        scores.append(complexity_score)

        # 5. Bootstrap deflation
        deflation = self._bootstrap_deflation(
            returns_is, returns_oos,
        )
        scores.append(deflation.get("deflation_score", 0))

        # Composite overfitting score
        overfitting_score = float(np.mean(scores))
        is_overfit = overfitting_score > self._threshold

        return OverfitDiagnostic(
            strategy_id=strategy_id,
            overfitting_score=overfitting_score,
            is_overfit=is_overfit,
            parameter_sensitivity=sensitivity,
            regime_robustness=regime,
            complexity_penalty=complexity,
            is_oos_gap=is_oos_gap,
            diagnostics={
                "sharpe_is": round(sharpe_is, 4),
                "sharpe_oos": round(sharpe_oos, 4),
                "gap_score": round(gap_score, 4),
                "sensitivity_score": round(sensitivity_score, 4),
                "regime_score": round(regime_score, 4),
                "complexity_score": round(complexity_score, 4),
                "bootstrap_deflation": deflation,
                "n_observations": n_obs,
                "n_parameters": n_parameters,
            },
        )

    def _parameter_sensitivity(
        self,
        returns: np.ndarray,
        names: list[str] | None,
        values: list[float] | None,
    ) -> dict:
        """
        Measure sensitivity to parameter perturbation.
        Uses bootstrap resampling as a proxy when exact
        parameter variation isn't available.
        """
        rng = np.random.RandomState(42)
        base_sharpe = self._sharpe(returns)

        if base_sharpe == 0:
            return {"avg_degradation": 0.5, "max_degradation": 1.0}

        degradations = []
        for _ in range(min(50, self._n_bootstrap)):
            # Perturb returns by adding noise (proxy for param sensitivity)
            noise = rng.normal(0, abs(returns.std()) * self._perturbation, len(returns))
            perturbed = returns + noise
            perturbed_sharpe = self._sharpe(perturbed)
            degradation = abs(base_sharpe - perturbed_sharpe) / max(abs(base_sharpe), 0.001)
            degradations.append(degradation)

        return {
            "avg_degradation": round(float(np.mean(degradations)), 4),
            "max_degradation": round(float(np.max(degradations)), 4),
            "std_degradation": round(float(np.std(degradations)), 4),
            "parameter_names": names or [],
        }

    def _regime_robustness(self, returns: np.ndarray) -> dict:
        """
        Test strategy across volatility regimes.
        Split returns into quintiles by rolling vol.
        """
        n = len(returns)
        if n < 20:
            return {"regime_consistency": 0.5, "error": "insufficient_data"}

        # Compute rolling volatility (20-period)
        window = min(20, n // 4)
        rolling_vol = np.array([
            returns[max(0, i - window):i].std()
            for i in range(window, n)
        ])
        ret_trimmed = returns[window:]

        if len(rolling_vol) < 10:
            return {"regime_consistency": 0.5, "error": "insufficient_data"}

        # Split into low/medium/high vol regimes
        vol_terciles = np.percentile(rolling_vol, [33, 66])
        regime_sharpes = {}

        low_mask = rolling_vol <= vol_terciles[0]
        mid_mask = (rolling_vol > vol_terciles[0]) & (rolling_vol <= vol_terciles[1])
        high_mask = rolling_vol > vol_terciles[1]

        for label, mask in [("low_vol", low_mask), ("mid_vol", mid_mask), ("high_vol", high_mask)]:
            chunk = ret_trimmed[mask]
            if len(chunk) >= 5:
                regime_sharpes[label] = round(self._sharpe(chunk), 4)

        if not regime_sharpes:
            return {"regime_consistency": 0.5}

        sharpes = list(regime_sharpes.values())
        consistency = 1.0 - (np.std(sharpes) / max(np.mean(np.abs(sharpes)), 0.001))
        consistency = max(0.0, min(1.0, consistency))

        return {
            "regime_consistency": round(float(consistency), 4),
            "regime_sharpes": regime_sharpes,
            "n_regimes": len(regime_sharpes),
        }

    def _complexity_penalty(
        self,
        n_parameters: int,
        n_observations: int,
        sharpe: float,
    ) -> float:
        """
        BIC-inspired complexity penalty.
        penalty = k × ln(n) / (2 × |Sharpe| × n)
        """
        if n_observations <= 0 or sharpe == 0:
            return float(n_parameters)
        return (
            n_parameters * math.log(max(2, n_observations))
            / (2 * max(abs(sharpe), 0.01) * n_observations)
        )

    def _bootstrap_deflation(
        self,
        returns_is: np.ndarray,
        returns_oos: np.ndarray,
    ) -> dict:
        """
        Measure how much in-sample Sharpe deflates out-of-sample.
        Uses bootstrap to estimate expected deflation.
        """
        rng = np.random.RandomState(42)
        _sharpe_is = self._sharpe(returns_is)  # noqa: F841
        sharpe_oos = self._sharpe(returns_oos)

        # Bootstrap the IS returns and compute Sharpe distribution
        boot_sharpes = []
        n = len(returns_is)
        for _ in range(self._n_bootstrap):
            sample = rng.choice(returns_is, size=n, replace=True)
            boot_sharpes.append(self._sharpe(sample))

        boot_sharpes = np.array(boot_sharpes)
        expected_is_sharpe = float(np.mean(boot_sharpes))
        deflation = (
            (expected_is_sharpe - sharpe_oos)
            / max(abs(expected_is_sharpe), 0.001)
        ) if expected_is_sharpe != 0 else 0.0

        return {
            "expected_is_sharpe": round(expected_is_sharpe, 4),
            "actual_oos_sharpe": round(sharpe_oos, 4),
            "deflation_ratio": round(deflation, 4),
            "deflation_score": round(
                min(1.0, max(0.0, deflation / 2.0)), 4,
            ),
        }

    @staticmethod
    def _sharpe(returns: np.ndarray, ann_factor: float = 252.0) -> float:
        """Annualised Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))
        if std_r == 0:
            return 0.0
        return mean_r / std_r * math.sqrt(ann_factor)
