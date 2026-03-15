"""
System Validation Report Generator (Step 12).

Generates a comprehensive automated validation report covering
all aspects of strategy evaluation:

  - Performance metrics (Sharpe, Sortino, Calmar)
  - Risk metrics (max drawdown, risk of ruin, VaR)
  - Bias audit results
  - Stability score
  - Stress test results
  - Governance status
  - Reproducibility verification
  - Overall system health grade

Output: JSON report + human-readable summary.
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
class ValidationReport:
    """Comprehensive system validation report."""
    report_id: str
    timestamp: str
    overall_grade: str       # A, B, C, D, F
    overall_score: float     # [0, 100]
    sections: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp,
            "overall_grade": self.overall_grade,
            "overall_score": round(self.overall_score, 2),
            "sections": self.sections,
            "warnings": self.warnings,
            "failures": self.failures,
            "recommendations": self.recommendations,
        }


class ValidationReportGenerator:
    """
    Generates automated validation reports for strategies.

    Usage:
        generator = ValidationReportGenerator()
        report = generator.generate(
            strategy_id="my_strat",
            returns=returns_array,
            bias_audit=bias_result,
            stress_results=stress_results,
            governance=governance_record,
        )
    """

    def __init__(self) -> None:
        self._report_counter = 0

    def generate(
        self,
        strategy_id: str,
        returns: np.ndarray,
        initial_capital: float = 10000.0,
        bias_audit: Optional[dict] = None,
        stress_results: Optional[list[dict]] = None,
        stability_score: Optional[float] = None,
        governance: Optional[dict] = None,
        overfit_diagnostic: Optional[dict] = None,
    ) -> ValidationReport:
        """Generate a comprehensive validation report."""
        self._report_counter += 1
        report_id = f"val_{strategy_id}_{self._report_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        sections: dict = {}
        section_scores: list[float] = []
        warnings: list[str] = []
        failures: list[str] = []
        recommendations: list[str] = []

        # 1. Performance metrics
        perf = self._performance_section(returns, initial_capital)
        sections["performance"] = perf
        section_scores.append(perf.get("score", 50))

        # 2. Risk metrics
        risk = self._risk_section(returns, initial_capital)
        sections["risk"] = risk
        section_scores.append(risk.get("score", 50))

        # 3. Bias audit
        if bias_audit:
            bias_section = self._bias_section(bias_audit)
            sections["bias_audit"] = bias_section
            section_scores.append(bias_section.get("score", 50))
            if bias_audit.get("bias_risk_score", 0) > 0.5:
                failures.append(
                    f"Bias risk score {bias_audit['bias_risk_score']:.3f} "
                    "exceeds threshold"
                )
        else:
            sections["bias_audit"] = {"status": "not_performed", "score": 30}
            section_scores.append(30)
            warnings.append("Bias audit not performed")

        # 4. Stability
        if stability_score is not None:
            stab_score = stability_score * 100
            sections["stability"] = {
                "stability_score": stability_score,
                "score": stab_score,
                "status": "stable" if stability_score > 0.6 else "unstable",
            }
            section_scores.append(stab_score)
            if stability_score < 0.4:
                failures.append(
                    f"Stability score {stability_score:.3f} below threshold"
                )
        else:
            sections["stability"] = {"status": "not_tested", "score": 30}
            section_scores.append(30)
            warnings.append("Stability not tested")

        # 5. Stress testing
        if stress_results:
            stress_section = self._stress_section(stress_results)
            sections["stress_testing"] = stress_section
            section_scores.append(stress_section.get("score", 50))
        else:
            sections["stress_testing"] = {"status": "not_performed", "score": 30}
            section_scores.append(30)
            warnings.append("Stress testing not performed")

        # 6. Overfitting
        if overfit_diagnostic:
            overfit_section = self._overfit_section(overfit_diagnostic)
            sections["overfitting"] = overfit_section
            section_scores.append(overfit_section.get("score", 50))
            if overfit_diagnostic.get("is_overfit", False):
                failures.append("Strategy flagged as overfit")
        else:
            sections["overfitting"] = {"status": "not_checked", "score": 40}
            section_scores.append(40)

        # 7. Governance
        if governance:
            gov_section = self._governance_section(governance)
            sections["governance"] = gov_section
            section_scores.append(gov_section.get("score", 50))
        else:
            sections["governance"] = {"status": "not_registered", "score": 20}
            section_scores.append(20)
            warnings.append("Strategy not registered in governance system")

        # Overall score and grade
        overall_score = float(np.mean(section_scores))
        overall_grade = self._score_to_grade(overall_score)

        # Generate recommendations
        if overall_score < 50:
            recommendations.append(
                "Strategy does not meet minimum validation threshold"
            )
        bias_status = sections.get("bias_audit", {}).get("status")
        if "bias_audit" not in sections or bias_status == "not_performed":
            recommendations.append("Run bias audit before deployment")
        if not stress_results:
            recommendations.append("Run stress tests before deployment")

        report = ValidationReport(
            report_id=report_id,
            timestamp=ts,
            overall_grade=overall_grade,
            overall_score=overall_score,
            sections=sections,
            warnings=warnings,
            failures=failures,
            recommendations=recommendations,
        )

        logger.info(
            "Validation report %s: grade=%s score=%.1f failures=%d",
            report_id, overall_grade, overall_score, len(failures),
        )
        return report

    def _performance_section(
        self, returns: np.ndarray, capital: float,
    ) -> dict:
        """Compute performance metrics."""
        n = len(returns)
        if n < 2:
            return {"score": 0, "error": "insufficient_data"}

        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))

        # Sharpe
        sharpe = mean_r / std_r * np.sqrt(252) if std_r > 0 else 0.0

        # Sortino
        downside = returns[returns < 0]
        downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else std_r
        sortino = mean_r / downside_std * np.sqrt(252) if downside_std > 0 else 0.0

        # Total return
        equity = capital * np.cumprod(1 + returns)
        total_return = float((equity[-1] / capital - 1) * 100)

        # Win rate
        hit_rate = float(np.mean(returns > 0) * 100)

        # Score: based on Sharpe ratio
        score = min(100, max(0, sharpe * 30 + 40))

        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "total_return_pct": round(total_return, 4),
            "hit_rate_pct": round(hit_rate, 2),
            "mean_return_pct": round(mean_r * 100, 4),
            "volatility_pct": round(std_r * 100 * np.sqrt(252), 4),
            "n_observations": n,
            "score": round(score, 2),
        }

    def _risk_section(
        self, returns: np.ndarray, capital: float,
    ) -> dict:
        """Compute risk metrics."""
        if len(returns) < 2:
            return {"score": 0, "error": "insufficient_data"}

        equity = capital * np.cumprod(1 + returns)
        peak = np.maximum.accumulate(equity)
        drawdowns = (peak - equity) / peak
        max_dd = float(np.max(drawdowns))

        # Calmar
        ann_return = float(np.mean(returns)) * 252
        calmar = ann_return / max(max_dd, 0.001)

        # VaR 95%
        var_95 = float(np.percentile(returns, 5))

        # CVaR (Expected Shortfall)
        cvar = float(np.mean(returns[returns <= var_95]))

        # Risk of ruin
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))
        edge = mean_r / std_r if std_r > 0 else 0
        if -1 < edge < 1 and edge != 0:
            try:
                ror = ((1 - edge) / (1 + edge)) ** 20
            except (OverflowError, ZeroDivisionError):
                ror = 0.5
        else:
            ror = 0.0 if edge >= 1 else 1.0

        # Score: lower drawdown = better
        dd_score = max(0, 100 - max_dd * 500)
        score = min(100, max(0, dd_score))

        return {
            "max_drawdown_pct": round(max_dd * 100, 4),
            "calmar_ratio": round(calmar, 4),
            "var_95_pct": round(var_95 * 100, 4),
            "cvar_95_pct": round(cvar * 100, 4),
            "risk_of_ruin": round(ror, 6),
            "score": round(score, 2),
        }

    def _bias_section(self, audit: dict) -> dict:
        """Score bias audit results."""
        risk_score = audit.get("bias_risk_score", 0.5)
        score = max(0, 100 - risk_score * 100)
        return {
            "bias_risk_score": risk_score,
            "risk_level": audit.get("risk_level", "unknown"),
            "flags": audit.get("checks_failed", 0),
            "score": round(score, 2),
        }

    def _stress_section(self, results: list[dict]) -> dict:
        """Score stress test results."""
        survived = sum(1 for r in results if r.get("survived", False))
        total = len(results)
        survival_rate = survived / max(total, 1)
        worst_dd = max(
            (r.get("max_drawdown_pct", 0) for r in results), default=0,
        )
        score = survival_rate * 80 + (1 - min(worst_dd, 1)) * 20
        return {
            "scenarios_tested": total,
            "survived": survived,
            "survival_rate": round(survival_rate, 4),
            "worst_drawdown_pct": round(worst_dd * 100, 4),
            "score": round(score, 2),
        }

    def _overfit_section(self, diagnostic: dict) -> dict:
        """Score overfitting diagnostic."""
        overfit_score = diagnostic.get("overfitting_score", 0.5)
        score = max(0, 100 - overfit_score * 100)
        return {
            "overfitting_score": overfit_score,
            "is_overfit": diagnostic.get("is_overfit", False),
            "score": round(score, 2),
        }

    def _governance_section(self, governance: dict) -> dict:
        """Score governance status."""
        status = governance.get("status", "DRAFT")
        score_map = {
            "APPROVED": 100,
            "UNDER_REVIEW": 60,
            "DRAFT": 30,
            "REJECTED": 10,
            "RETIRED": 20,
        }
        score = score_map.get(status, 30)
        return {
            "status": status,
            "deployment_stage": governance.get("deployment_stage", "RESEARCH"),
            "deployment_cleared": governance.get("deployment_cleared", False),
            "score": score,
        }

    @staticmethod
    def _score_to_grade(score: float) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 65:
            return "C"
        if score >= 50:
            return "D"
        return "F"

    def save_report(
        self,
        report: ValidationReport,
        output_dir: str = "results/validation",
    ) -> Path:
        """Save validation report."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{report.report_id}.json"
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        logger.info("Validation report saved: %s", path)
        return path
