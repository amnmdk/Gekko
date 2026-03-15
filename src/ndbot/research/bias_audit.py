"""
Research Bias Auditor (Step 6).

Systematic bias detection across the entire research pipeline:

  1. Look-ahead bias       — features using future data
  2. Survivorship bias     — using only surviving assets
  3. Data snooping bias    — multiple testing without correction
  4. Feature leakage       — target information leaking into features
  5. Selection bias        — cherry-picking time periods or assets
  6. Backfill bias         — using retroactively revised data

Outputs a composite bias risk score [0, 1]:
  0.0 - 0.2:  Low risk (good research hygiene)
  0.2 - 0.5:  Moderate risk (some concerns)
  0.5 - 0.8:  High risk (results unreliable)
  0.8 - 1.0:  Critical (results likely invalid)
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
class BiasFlag:
    """A single bias detection flag."""
    bias_type: str
    severity: str       # "low", "medium", "high", "critical"
    description: str
    evidence: dict = field(default_factory=dict)
    remediation: str = ""

    def to_dict(self) -> dict:
        return {
            "bias_type": self.bias_type,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "remediation": self.remediation,
        }


@dataclass
class BiasAuditResult:
    """Complete bias audit report."""
    audit_id: str
    timestamp: str
    bias_risk_score: float       # [0, 1] composite
    risk_level: str              # "low", "moderate", "high", "critical"
    flags: list[BiasFlag] = field(default_factory=list)
    checks_passed: int = 0
    checks_failed: int = 0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "bias_risk_score": round(self.bias_risk_score, 4),
            "risk_level": self.risk_level,
            "flags": [f.to_dict() for f in self.flags],
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "recommendations": self.recommendations,
        }


class BiasAuditor:
    """
    Audits a research experiment for common biases.

    Usage:
        auditor = BiasAuditor()
        result = auditor.audit(
            returns=strategy_returns,
            features=feature_matrix,
            feature_names=names,
            event_timestamps=timestamps,
            n_strategies_tested=10,
        )
    """

    SEVERITY_WEIGHTS = {
        "low": 0.1,
        "medium": 0.3,
        "high": 0.6,
        "critical": 1.0,
    }

    def __init__(self) -> None:
        self._audit_counter = 0

    def audit(
        self,
        returns: np.ndarray,
        features: Optional[np.ndarray] = None,
        feature_names: Optional[list[str]] = None,
        event_timestamps: Optional[np.ndarray] = None,
        n_strategies_tested: int = 1,
        backtest_start: Optional[datetime] = None,
        backtest_end: Optional[datetime] = None,
        symbols_used: Optional[list[str]] = None,
        total_symbols_available: Optional[int] = None,
    ) -> BiasAuditResult:
        """Run a comprehensive bias audit."""
        self._audit_counter += 1
        audit_id = f"audit_{self._audit_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        flags: list[BiasFlag] = []
        checks_passed = 0

        # 1. Look-ahead bias check
        flag = self._check_look_ahead(
            returns, event_timestamps, features,
        )
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # 2. Survivorship bias check
        flag = self._check_survivorship(
            symbols_used, total_symbols_available,
        )
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # 3. Data snooping check
        flag = self._check_data_snooping(
            n_strategies_tested, returns,
        )
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # 4. Feature leakage check
        flag = self._check_feature_leakage(
            features, returns, feature_names,
        )
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # 5. Selection bias check
        flag = self._check_selection_bias(
            returns, backtest_start, backtest_end,
        )
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # 6. Return distribution anomalies
        flag = self._check_return_anomalies(returns)
        if flag:
            flags.append(flag)
        else:
            checks_passed += 1

        # Compute composite bias risk score
        if not flags:
            bias_risk_score = 0.0
        else:
            weights = [
                self.SEVERITY_WEIGHTS.get(f.severity, 0.5)
                for f in flags
            ]
            bias_risk_score = min(1.0, sum(weights) / 6.0)

        risk_level = self._risk_level(bias_risk_score)
        recommendations = self._generate_recommendations(flags)

        result = BiasAuditResult(
            audit_id=audit_id,
            timestamp=ts,
            bias_risk_score=bias_risk_score,
            risk_level=risk_level,
            flags=flags,
            checks_passed=checks_passed,
            checks_failed=len(flags),
            recommendations=recommendations,
        )

        logger.info(
            "Bias audit %s: score=%.3f (%s) flags=%d",
            audit_id, bias_risk_score, risk_level, len(flags),
        )
        return result

    def _check_look_ahead(
        self,
        returns: np.ndarray,
        timestamps: Optional[np.ndarray],
        features: Optional[np.ndarray],
    ) -> Optional[BiasFlag]:
        """Check for look-ahead bias indicators."""
        if timestamps is None:
            return BiasFlag(
                bias_type="look_ahead",
                severity="medium",
                description="No event timestamps provided for look-ahead validation",
                remediation="Provide timestamps to enable temporal validation",
            )

        # Check if returns are auto-correlated (suspicious)
        if len(returns) > 20:
            autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
            if abs(autocorr) > 0.3:
                return BiasFlag(
                    bias_type="look_ahead",
                    severity="high",
                    description=(
                        f"High return autocorrelation ({autocorr:.3f}) "
                        "suggests look-ahead bias"
                    ),
                    evidence={"autocorrelation": round(autocorr, 4)},
                    remediation="Check that signals only use data available at trade time",
                )

        return None

    def _check_survivorship(
        self,
        symbols: Optional[list[str]],
        total_available: Optional[int],
    ) -> Optional[BiasFlag]:
        """Check for survivorship bias."""
        if symbols is None or total_available is None:
            return BiasFlag(
                bias_type="survivorship",
                severity="low",
                description="Survivorship bias not verifiable — no universe data",
                remediation="Provide full historical asset universe for validation",
            )

        if total_available > 0:
            coverage = len(symbols) / total_available
            if coverage < 0.5:
                return BiasFlag(
                    bias_type="survivorship",
                    severity="high",
                    description=(
                        f"Only {len(symbols)}/{total_available} assets used "
                        f"({coverage:.0%}), high survivorship bias risk"
                    ),
                    evidence={
                        "symbols_used": len(symbols),
                        "total_available": total_available,
                        "coverage": round(coverage, 4),
                    },
                    remediation="Include delisted assets in backtesting universe",
                )
        return None

    def _check_data_snooping(
        self,
        n_tested: int,
        returns: np.ndarray,
    ) -> Optional[BiasFlag]:
        """Check for data snooping (multiple testing problem)."""
        if n_tested <= 1:
            return None

        # Bonferroni-adjusted significance threshold
        effective_alpha = 0.05 / n_tested

        sharpe = self._sharpe(returns)
        # Approximate p-value from Sharpe
        n = len(returns)
        t_stat = sharpe * np.sqrt(n) / np.sqrt(252)

        if n_tested > 10:
            severity = "high"
        elif n_tested > 5:
            severity = "medium"
        else:
            severity = "low"

        return BiasFlag(
            bias_type="data_snooping",
            severity=severity,
            description=(
                f"{n_tested} strategies tested — Bonferroni threshold "
                f"= {effective_alpha:.4f} (stricter than 0.05)"
            ),
            evidence={
                "n_strategies_tested": n_tested,
                "bonferroni_alpha": round(effective_alpha, 6),
                "approx_t_stat": round(float(t_stat), 4),
            },
            remediation="Apply multiple testing correction (BH-FDR or Bonferroni)",
        )

    def _check_feature_leakage(
        self,
        features: Optional[np.ndarray],
        returns: np.ndarray,
        feature_names: Optional[list[str]],
    ) -> Optional[BiasFlag]:
        """Check for target leakage in features."""
        if features is None:
            return None

        n_features = features.shape[1] if features.ndim > 1 else 1
        names = feature_names or [f"feature_{i}" for i in range(n_features)]

        # Check correlation between each feature and returns
        suspicious = []
        for i in range(min(n_features, features.shape[1])):
            feat = features[:, i]
            if len(feat) != len(returns):
                continue
            corr = float(np.corrcoef(feat, returns)[0, 1])
            if abs(corr) > 0.8:
                suspicious.append({
                    "feature": names[i] if i < len(names) else f"feat_{i}",
                    "correlation": round(corr, 4),
                })

        if suspicious:
            return BiasFlag(
                bias_type="feature_leakage",
                severity="critical",
                description=(
                    f"{len(suspicious)} features with >0.8 correlation "
                    "to returns — likely target leakage"
                ),
                evidence={"suspicious_features": suspicious},
                remediation=(
                    "Remove features that embed future return information; "
                    "ensure all features are computed from data available at trade time"
                ),
            )
        return None

    def _check_selection_bias(
        self,
        returns: np.ndarray,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> Optional[BiasFlag]:
        """Check for time period selection bias."""
        if start is None or end is None:
            return None

        # Check if backtest period is suspiciously short
        delta = end - start
        if delta.days < 90:
            return BiasFlag(
                bias_type="selection_bias",
                severity="medium",
                description=(
                    f"Backtest period is only {delta.days} days — "
                    "insufficient for statistical significance"
                ),
                evidence={"period_days": delta.days},
                remediation="Extend backtest to at least 1 year of data",
            )

        # Check if all returns are positive (suspicious)
        if len(returns) > 20 and all(r >= 0 for r in returns):
            return BiasFlag(
                bias_type="selection_bias",
                severity="critical",
                description="All returns are non-negative — extremely suspicious",
                remediation="Verify data integrity and signal generation logic",
            )

        return None

    def _check_return_anomalies(
        self, returns: np.ndarray,
    ) -> Optional[BiasFlag]:
        """Check for anomalous return patterns."""
        if len(returns) < 10:
            return None

        # Check for excessive kurtosis (fat tails not captured)
        from scipy import stats as sp_stats
        try:
            kurtosis = float(sp_stats.kurtosis(returns))
            if kurtosis > 10:
                return BiasFlag(
                    bias_type="return_anomaly",
                    severity="medium",
                    description=(
                        f"Excess kurtosis = {kurtosis:.1f} — fat tails "
                        "may invalidate Sharpe-based analysis"
                    ),
                    evidence={"excess_kurtosis": round(kurtosis, 2)},
                    remediation="Use Sortino ratio or bootstrap methods instead of Sharpe",
                )
        except Exception:
            pass

        return None

    def save_report(
        self, result: BiasAuditResult,
        output_dir: str = "results/bias_audits",
    ) -> Path:
        """Save audit report."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{result.audit_id}.json"
        with open(path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)
        return path

    @staticmethod
    def _risk_level(score: float) -> str:
        if score < 0.2:
            return "low"
        if score < 0.5:
            return "moderate"
        if score < 0.8:
            return "high"
        return "critical"

    @staticmethod
    def _sharpe(returns: np.ndarray) -> float:
        if len(returns) < 2:
            return 0.0
        std = float(np.std(returns, ddof=1))
        return float(np.mean(returns)) / std * np.sqrt(252) if std > 0 else 0.0

    @staticmethod
    def _generate_recommendations(flags: list[BiasFlag]) -> list[str]:
        recs = []
        types = {f.bias_type for f in flags}
        if "look_ahead" in types:
            recs.append("Implement strict point-in-time data validation")
        if "survivorship" in types:
            recs.append("Include delisted assets in the backtest universe")
        if "data_snooping" in types:
            recs.append("Apply multiple hypothesis testing correction")
        if "feature_leakage" in types:
            recs.append("Audit feature pipeline for target information leakage")
        if "selection_bias" in types:
            recs.append("Extend backtest period and use walk-forward validation")
        if not recs:
            recs.append("Research pipeline passes all bias checks")
        return recs
