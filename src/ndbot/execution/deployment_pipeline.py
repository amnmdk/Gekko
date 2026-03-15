"""
Safe Deployment Pipeline (Step 9).

Stage-gated promotion system ensuring strategies pass
risk thresholds before advancing:

  Stage 1: RESEARCH     — backtest + event study + bias audit
  Stage 2: SIMULATION   — synthetic data simulation + stress test
  Stage 3: PAPER        — paper trading with live data, no real capital
  Stage 4: LIMITED      — real capital, max 10% of allocation
  Stage 5: FULL         — full capital deployment

Each transition requires:
  - Minimum Sharpe ratio
  - Maximum drawdown threshold
  - Bias audit passing
  - Governance approval
  - Minimum observation period
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Stage(str, Enum):
    RESEARCH = "RESEARCH"
    SIMULATION = "SIMULATION"
    PAPER = "PAPER"
    LIMITED = "LIMITED"
    FULL = "FULL"


STAGE_ORDER = [
    Stage.RESEARCH,
    Stage.SIMULATION,
    Stage.PAPER,
    Stage.LIMITED,
    Stage.FULL,
]


@dataclass
class StageRequirements:
    """Requirements to enter a stage."""
    min_sharpe: float = 0.0
    max_drawdown_pct: float = 1.0
    min_trades: int = 0
    min_observation_days: int = 0
    bias_audit_required: bool = False
    max_bias_score: float = 1.0
    stress_test_required: bool = False
    governance_approval: bool = False
    max_capital_fraction: float = 1.0


# Default requirements for each stage transition
STAGE_REQUIREMENTS: dict[Stage, StageRequirements] = {
    Stage.RESEARCH: StageRequirements(),
    Stage.SIMULATION: StageRequirements(
        min_sharpe=0.3,
        max_drawdown_pct=0.30,
        min_trades=20,
    ),
    Stage.PAPER: StageRequirements(
        min_sharpe=0.5,
        max_drawdown_pct=0.20,
        min_trades=50,
        min_observation_days=7,
        bias_audit_required=True,
        max_bias_score=0.5,
        stress_test_required=True,
    ),
    Stage.LIMITED: StageRequirements(
        min_sharpe=0.8,
        max_drawdown_pct=0.15,
        min_trades=100,
        min_observation_days=30,
        bias_audit_required=True,
        max_bias_score=0.3,
        stress_test_required=True,
        governance_approval=True,
        max_capital_fraction=0.10,
    ),
    Stage.FULL: StageRequirements(
        min_sharpe=1.0,
        max_drawdown_pct=0.12,
        min_trades=200,
        min_observation_days=90,
        bias_audit_required=True,
        max_bias_score=0.2,
        stress_test_required=True,
        governance_approval=True,
        max_capital_fraction=1.0,
    ),
}


@dataclass
class PromotionCheck:
    """Result of checking if a strategy can be promoted."""
    strategy_id: str
    current_stage: Stage
    target_stage: Stage
    can_promote: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "current_stage": self.current_stage.value,
            "target_stage": self.target_stage.value,
            "can_promote": self.can_promote,
            "failures": self.failures,
            "metrics": self.metrics,
        }


@dataclass
class DeploymentRecord:
    """Tracks a strategy's deployment state."""
    strategy_id: str
    current_stage: Stage = Stage.RESEARCH
    stage_history: list[dict] = field(default_factory=list)
    created_at: str = ""
    last_promoted: str = ""
    metrics_history: dict = field(default_factory=dict)
    capital_fraction: float = 0.0
    is_active: bool = True

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "current_stage": self.current_stage.value,
            "stage_history": self.stage_history,
            "created_at": self.created_at,
            "last_promoted": self.last_promoted,
            "metrics_history": self.metrics_history,
            "capital_fraction": self.capital_fraction,
            "is_active": self.is_active,
        }


class DeploymentPipeline:
    """
    Manages stage-gated strategy deployment.

    Usage:
        pipeline = DeploymentPipeline()
        pipeline.register("my_strat")
        check = pipeline.check_promotion("my_strat", metrics)
        if check.can_promote:
            pipeline.promote("my_strat")
    """

    def __init__(self, storage_dir: str = "data/deployments"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, DeploymentRecord] = {}
        self._load()

    def _load(self) -> None:
        for path in self._dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                rec = DeploymentRecord(
                    strategy_id=data["strategy_id"],
                    current_stage=Stage(data.get("current_stage", "RESEARCH")),
                    stage_history=data.get("stage_history", []),
                    created_at=data.get("created_at", ""),
                    last_promoted=data.get("last_promoted", ""),
                    capital_fraction=data.get("capital_fraction", 0.0),
                    is_active=data.get("is_active", True),
                )
                self._records[rec.strategy_id] = rec
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load deployment: %s", exc)

    def _save(self, record: DeploymentRecord) -> None:
        path = self._dir / f"{record.strategy_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, default=str)

    def register(self, strategy_id: str) -> DeploymentRecord:
        """Register a strategy in the deployment pipeline."""
        rec = DeploymentRecord(strategy_id=strategy_id)
        self._records[strategy_id] = rec
        self._save(rec)
        return rec

    def check_promotion(
        self,
        strategy_id: str,
        metrics: dict,
        bias_score: float = 1.0,
        stress_passed: bool = False,
        governance_approved: bool = False,
    ) -> PromotionCheck:
        """
        Check if a strategy meets requirements for the next stage.

        Parameters
        ----------
        metrics : dict
            Must include: sharpe_ratio, max_drawdown_pct, total_trades,
            observation_days.
        """
        rec = self._records.get(strategy_id)
        if not rec:
            return PromotionCheck(
                strategy_id=strategy_id,
                current_stage=Stage.RESEARCH,
                target_stage=Stage.SIMULATION,
                can_promote=False,
                failures=["strategy_not_registered"],
            )

        current_idx = STAGE_ORDER.index(rec.current_stage)
        if current_idx >= len(STAGE_ORDER) - 1:
            return PromotionCheck(
                strategy_id=strategy_id,
                current_stage=rec.current_stage,
                target_stage=rec.current_stage,
                can_promote=False,
                failures=["already_at_final_stage"],
            )

        target = STAGE_ORDER[current_idx + 1]
        reqs = STAGE_REQUIREMENTS[target]
        failures = []

        sharpe = metrics.get("sharpe_ratio", 0)
        if sharpe < reqs.min_sharpe:
            failures.append(
                f"sharpe={sharpe:.3f} < {reqs.min_sharpe}",
            )

        dd = metrics.get("max_drawdown_pct", 1.0)
        if dd > reqs.max_drawdown_pct:
            failures.append(
                f"drawdown={dd:.3f} > {reqs.max_drawdown_pct}",
            )

        trades = metrics.get("total_trades", 0)
        if trades < reqs.min_trades:
            failures.append(
                f"trades={trades} < {reqs.min_trades}",
            )

        obs_days = metrics.get("observation_days", 0)
        if obs_days < reqs.min_observation_days:
            failures.append(
                f"obs_days={obs_days} < {reqs.min_observation_days}",
            )

        if reqs.bias_audit_required and bias_score > reqs.max_bias_score:
            failures.append(
                f"bias_score={bias_score:.3f} > {reqs.max_bias_score}",
            )

        if reqs.stress_test_required and not stress_passed:
            failures.append("stress_test_not_passed")

        if reqs.governance_approval and not governance_approved:
            failures.append("governance_not_approved")

        return PromotionCheck(
            strategy_id=strategy_id,
            current_stage=rec.current_stage,
            target_stage=target,
            can_promote=len(failures) == 0,
            failures=failures,
            metrics=metrics,
        )

    def promote(self, strategy_id: str) -> tuple[bool, str]:
        """Promote strategy to the next stage."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "not_found"

        current_idx = STAGE_ORDER.index(rec.current_stage)
        if current_idx >= len(STAGE_ORDER) - 1:
            return False, "already_at_final_stage"

        new_stage = STAGE_ORDER[current_idx + 1]
        now = datetime.now(timezone.utc).isoformat()

        rec.stage_history.append({
            "from": rec.current_stage.value,
            "to": new_stage.value,
            "timestamp": now,
        })
        rec.current_stage = new_stage
        rec.last_promoted = now
        rec.capital_fraction = STAGE_REQUIREMENTS[new_stage].max_capital_fraction

        self._save(rec)
        logger.info(
            "Strategy %s promoted: %s → %s",
            strategy_id, STAGE_ORDER[current_idx].value, new_stage.value,
        )
        return True, new_stage.value

    def demote(self, strategy_id: str, reason: str = "") -> tuple[bool, str]:
        """Demote strategy back to RESEARCH (emergency)."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "not_found"

        now = datetime.now(timezone.utc).isoformat()
        rec.stage_history.append({
            "from": rec.current_stage.value,
            "to": Stage.RESEARCH.value,
            "timestamp": now,
            "reason": reason,
        })
        rec.current_stage = Stage.RESEARCH
        rec.capital_fraction = 0.0
        rec.last_promoted = now
        self._save(rec)
        logger.warning("Strategy %s demoted to RESEARCH: %s", strategy_id, reason)
        return True, "demoted"

    def get(self, strategy_id: str) -> Optional[DeploymentRecord]:
        return self._records.get(strategy_id)

    def active_deployments(self) -> list[DeploymentRecord]:
        return [r for r in self._records.values() if r.is_active]

    def summary(self) -> dict:
        by_stage: dict[str, int] = {}
        for r in self._records.values():
            by_stage[r.current_stage.value] = (
                by_stage.get(r.current_stage.value, 0) + 1
            )
        return {
            "total_strategies": len(self._records),
            "active": sum(1 for r in self._records.values() if r.is_active),
            "by_stage": by_stage,
        }
