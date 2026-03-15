"""
Alpha Signal Discovery Engine (Step 6).

Discovers tradeable alpha signals from event features using:
  1. Logistic regression — baseline linear model
  2. Gradient boosting   — non-linear feature interactions
  3. Feature importance   — SHAP-style permutation importance

Each model predicts: P(positive return at horizon H | event features).
Signals with t-stat > 2 and Sharpe > 0.5 are flagged as candidates.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AlphaSignal:
    """A discovered alpha signal candidate."""
    signal_id: str
    name: str
    description: str
    model_type: str  # "logistic" or "gradient_boosting"
    horizon: str  # e.g., "1h"
    features_used: list[str] = field(default_factory=list)
    sharpe_ratio: float = 0.0
    hit_rate: float = 0.5
    t_statistic: float = 0.0
    p_value: float = 1.0
    mean_return_pct: float = 0.0
    n_samples: int = 0
    feature_importance: dict[str, float] = field(default_factory=dict)
    is_significant: bool = False

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "name": self.name,
            "description": self.description,
            "model_type": self.model_type,
            "horizon": self.horizon,
            "features_used": self.features_used,
            "sharpe_ratio": self.sharpe_ratio,
            "hit_rate": self.hit_rate,
            "t_statistic": self.t_statistic,
            "p_value": self.p_value,
            "mean_return_pct": self.mean_return_pct,
            "n_samples": self.n_samples,
            "feature_importance": self.feature_importance,
            "is_significant": self.is_significant,
        }


class AlphaDiscoveryEngine:
    """
    Runs alpha signal discovery experiments.

    Takes feature matrices (from NewsFeatureEngine) and return series
    (from EventReactionAnalyser) and discovers predictive relationships.
    """

    HORIZONS = ["5m", "15m", "1h", "4h", "1d"]
    SIGNIFICANCE_THRESHOLD = 0.05
    MIN_SHARPE = 0.3
    MIN_SAMPLES = 20

    def __init__(self) -> None:
        self._signals: list[AlphaSignal] = []

    def discover(
        self,
        features: np.ndarray,
        returns: dict[str, np.ndarray],
        feature_names: list[str],
        output_dir: str = "results/alpha_signals",
    ) -> list[AlphaSignal]:
        """
        Run full alpha discovery pipeline.

        Parameters
        ----------
        features : np.ndarray
            (N, D) feature matrix from NewsFeatureEngine.
        returns : dict[str, np.ndarray]
            Horizon label -> (N,) return array.
        feature_names : list[str]
            Names of the D features.
        output_dir : str
            Directory for output files.

        Returns
        -------
        list[AlphaSignal] — discovered candidate signals.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        signals: list[AlphaSignal] = []

        for horizon, ret_series in returns.items():
            if len(ret_series) < self.MIN_SAMPLES:
                logger.info(
                    "Skipping %s: only %d samples",
                    horizon, len(ret_series),
                )
                continue

            # Binary labels: positive return = 1
            labels = (ret_series > 0).astype(int)

            # 1. Logistic regression
            lr_signal = self._run_logistic(
                features, labels, ret_series,
                feature_names, horizon,
            )
            if lr_signal:
                signals.append(lr_signal)

            # 2. Gradient boosting
            gb_signal = self._run_gradient_boosting(
                features, labels, ret_series,
                feature_names, horizon,
            )
            if gb_signal:
                signals.append(gb_signal)

            # 3. Univariate feature scans
            uni_signals = self._univariate_scan(
                features, ret_series, feature_names, horizon,
            )
            signals.extend(uni_signals)

        self._signals = signals

        # Save results
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report = {
            "timestamp": ts,
            "total_signals": len(signals),
            "significant_signals": sum(
                1 for s in signals if s.is_significant
            ),
            "signals": [s.to_dict() for s in signals],
        }
        json_path = out / f"alpha_signals_{ts}.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(
            "Alpha discovery: %d signals found (%d significant)",
            len(signals),
            sum(1 for s in signals if s.is_significant),
        )

        return signals

    def _run_logistic(
        self,
        feat_matrix: np.ndarray,
        y: np.ndarray,
        returns: np.ndarray,
        feature_names: list[str],
        horizon: str,
    ) -> Optional[AlphaSignal]:
        """Fit logistic regression and evaluate signal quality."""
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.model_selection import cross_val_predict
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            logger.debug("sklearn not available, skipping logistic")
            return None

        scaler = StandardScaler()
        scaled = scaler.fit_transform(feat_matrix)

        model = LogisticRegression(
            max_iter=500, C=0.1, penalty="l2",
            solver="lbfgs", random_state=42,
        )

        try:
            # Cross-validated predictions
            preds = cross_val_predict(
                model, scaled, y, cv=5, method="predict_proba",
            )
            pred_proba = preds[:, 1]

            # Fit full model for feature importance
            model.fit(scaled, y)
            coefs = dict(zip(
                feature_names,
                [round(float(c), 4) for c in model.coef_[0]],
            ))

            # Evaluate signal: use predictions as position sizing
            signal_returns = self._evaluate_signal(
                pred_proba, returns, threshold=0.55,
            )
            if signal_returns is None:
                return None

            return AlphaSignal(
                signal_id=f"lr_{horizon}",
                name=f"Logistic Regression ({horizon})",
                description=(
                    f"L2-regularised logistic regression on {len(feature_names)} "
                    f"features, predicting {horizon} return direction"
                ),
                model_type="logistic",
                horizon=horizon,
                features_used=feature_names,
                feature_importance=coefs,
                **signal_returns,
            )
        except Exception as exc:
            logger.debug("Logistic regression failed: %s", exc)
            return None

    def _run_gradient_boosting(
        self,
        feat_matrix: np.ndarray,
        y: np.ndarray,
        returns: np.ndarray,
        feature_names: list[str],
        horizon: str,
    ) -> Optional[AlphaSignal]:
        """Fit gradient boosting and evaluate signal quality."""
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.model_selection import cross_val_predict
        except ImportError:
            logger.debug("sklearn not available, skipping GBM")
            return None

        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=3,
            learning_rate=0.05, subsample=0.8,
            random_state=42,
        )

        try:
            preds = cross_val_predict(
                model, feat_matrix, y, cv=5, method="predict_proba",
            )
            pred_proba = preds[:, 1]

            model.fit(feat_matrix, y)
            importances = dict(zip(
                feature_names,
                [round(float(i), 4) for i in model.feature_importances_],
            ))

            signal_returns = self._evaluate_signal(
                pred_proba, returns, threshold=0.55,
            )
            if signal_returns is None:
                return None

            return AlphaSignal(
                signal_id=f"gb_{horizon}",
                name=f"Gradient Boosting ({horizon})",
                description=(
                    f"GBM classifier on {len(feature_names)} features, "
                    f"predicting {horizon} return direction"
                ),
                model_type="gradient_boosting",
                horizon=horizon,
                features_used=feature_names,
                feature_importance=importances,
                **signal_returns,
            )
        except Exception as exc:
            logger.debug("Gradient boosting failed: %s", exc)
            return None

    def _univariate_scan(
        self,
        feat_matrix: np.ndarray,
        returns: np.ndarray,
        feature_names: list[str],
        horizon: str,
    ) -> list[AlphaSignal]:
        """
        Scan each feature individually for predictive power.
        Uses simple median split: long when feature > median.
        """
        signals = []
        for i, fname in enumerate(feature_names):
            feat = feat_matrix[:, i]
            median_val = float(np.median(feat))
            above = returns[feat > median_val]
            below = returns[feat <= median_val]

            if len(above) < 5 or len(below) < 5:
                continue

            diff = float(np.mean(above) - np.mean(below))
            pooled_std = float(np.sqrt(
                (np.var(above) + np.var(below)) / 2
            ))
            if pooled_std == 0:
                continue

            t_stat = diff / (pooled_std / np.sqrt(
                len(above) + len(below)
            ))

            mean_ret = float(np.mean(above))
            std_ret = float(np.std(above))
            sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
            hit = float(np.mean(above > 0))

            is_sig = (
                abs(t_stat) > 2.0
                and abs(sharpe) > self.MIN_SHARPE
            )

            if abs(t_stat) > 1.5:
                signals.append(AlphaSignal(
                    signal_id=f"uni_{fname}_{horizon}",
                    name=f"Univariate: {fname} ({horizon})",
                    description=(
                        f"Median split on {fname}: "
                        f"long when > {median_val:.2f}"
                    ),
                    model_type="univariate",
                    horizon=horizon,
                    features_used=[fname],
                    sharpe_ratio=round(sharpe, 4),
                    hit_rate=round(hit, 4),
                    t_statistic=round(t_stat, 4),
                    p_value=round(self._t_to_p(t_stat, len(returns)), 6),
                    mean_return_pct=round(mean_ret, 4),
                    n_samples=int(len(above)),
                    is_significant=is_sig,
                ))

        return signals

    def _evaluate_signal(
        self,
        pred_proba: np.ndarray,
        returns: np.ndarray,
        threshold: float = 0.55,
    ) -> Optional[dict]:
        """Evaluate a signal's trading performance."""
        # Only trade when model is confident
        trade_mask = pred_proba > threshold
        if trade_mask.sum() < self.MIN_SAMPLES:
            return None

        trade_returns = returns[trade_mask]
        mean_ret = float(np.mean(trade_returns))
        std_ret = float(np.std(trade_returns))
        n = int(len(trade_returns))

        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0
        t_stat = (
            mean_ret / (std_ret / np.sqrt(n)) if std_ret > 0 else 0.0
        )
        hit = float(np.mean(trade_returns > 0))
        p_val = self._t_to_p(t_stat, n)

        return {
            "sharpe_ratio": round(sharpe, 4),
            "hit_rate": round(hit, 4),
            "t_statistic": round(t_stat, 4),
            "p_value": round(p_val, 6),
            "mean_return_pct": round(mean_ret, 4),
            "n_samples": n,
            "is_significant": (
                p_val < self.SIGNIFICANCE_THRESHOLD
                and abs(sharpe) > self.MIN_SHARPE
            ),
        }

    @staticmethod
    def _t_to_p(t_stat: float, n: int) -> float:
        """Convert t-statistic to two-tailed p-value."""
        try:
            from scipy import stats as sp_stats
            return float(
                2 * (1 - sp_stats.t.cdf(abs(t_stat), max(1, n - 1)))
            )
        except ImportError:
            # Rough approximation without scipy
            return 0.05 if abs(t_stat) > 2.0 else 0.5

    @property
    def signals(self) -> list[AlphaSignal]:
        return list(self._signals)

    @property
    def significant_signals(self) -> list[AlphaSignal]:
        return [s for s in self._signals if s.is_significant]
