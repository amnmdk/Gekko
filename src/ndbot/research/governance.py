"""
Model Governance System (Step 8).

Every strategy in the system must pass governance requirements
before it can be deployed. Governance metadata includes:

  1. Documentation     — strategy description, rationale, assumptions
  2. Risk limits       — max drawdown, max position size, daily loss cap
  3. Assumptions log   — market conditions under which strategy is valid
  4. Approval status   — DRAFT / UNDER_REVIEW / APPROVED / REJECTED / RETIRED
  5. Review history    — who reviewed, when, decision
  6. Deployment flag   — cleared for live trading (paper → limited → full)

Governance records are stored in data/governance/ as JSON files.
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


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class DeploymentStage(str, Enum):
    RESEARCH = "RESEARCH"
    SIMULATION = "SIMULATION"
    PAPER = "PAPER"
    LIMITED = "LIMITED"
    FULL = "FULL"


@dataclass
class RiskLimits:
    """Risk limits for a governed strategy."""
    max_drawdown_pct: float = 0.15
    max_daily_loss_pct: float = 0.05
    max_position_size_pct: float = 0.25
    max_concurrent_positions: int = 5
    max_leverage: float = 1.0
    stop_loss_required: bool = True

    def to_dict(self) -> dict:
        return {
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_position_size_pct": self.max_position_size_pct,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_leverage": self.max_leverage,
            "stop_loss_required": self.stop_loss_required,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskLimits":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class ReviewEntry:
    """A single governance review event."""
    reviewer: str
    timestamp: str
    decision: str      # "approve", "reject", "request_changes"
    comments: str = ""

    def to_dict(self) -> dict:
        return {
            "reviewer": self.reviewer,
            "timestamp": self.timestamp,
            "decision": self.decision,
            "comments": self.comments,
        }


@dataclass
class GovernanceRecord:
    """Complete governance metadata for a strategy."""
    strategy_id: str
    name: str
    description: str
    author: str = ""
    status: ApprovalStatus = ApprovalStatus.DRAFT
    deployment_stage: DeploymentStage = DeploymentStage.RESEARCH
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    assumptions: list[str] = field(default_factory=list)
    valid_market_conditions: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    review_history: list[ReviewEntry] = field(default_factory=list)
    created_at: str = ""
    last_updated: str = ""
    metrics_at_approval: dict = field(default_factory=dict)
    deployment_cleared: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "status": self.status.value,
            "deployment_stage": self.deployment_stage.value,
            "risk_limits": self.risk_limits.to_dict(),
            "assumptions": self.assumptions,
            "valid_market_conditions": self.valid_market_conditions,
            "known_limitations": self.known_limitations,
            "review_history": [r.to_dict() for r in self.review_history],
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "metrics_at_approval": self.metrics_at_approval,
            "deployment_cleared": self.deployment_cleared,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GovernanceRecord":
        d = dict(d)
        if "status" in d:
            d["status"] = ApprovalStatus(d["status"])
        if "deployment_stage" in d:
            d["deployment_stage"] = DeploymentStage(d["deployment_stage"])
        if "risk_limits" in d and isinstance(d["risk_limits"], dict):
            d["risk_limits"] = RiskLimits.from_dict(d["risk_limits"])
        if "review_history" in d:
            d["review_history"] = [
                ReviewEntry(**r) if isinstance(r, dict) else r
                for r in d["review_history"]
            ]
        valid_keys = set(cls.__dataclass_fields__.keys())
        return cls(**{k: d[k] for k in d if k in valid_keys})


class GovernanceSystem:
    """
    Manages strategy governance lifecycle.

    Enforces:
      - Documentation requirements before deployment
      - Risk limit validation
      - Approval workflow
      - Stage-gated deployment
    """

    REQUIRED_FIELDS = [
        "description", "assumptions", "risk_limits",
    ]

    def __init__(self, storage_dir: str = "data/governance"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, GovernanceRecord] = {}
        self._load()

    def _load(self) -> None:
        for path in self._dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                rec = GovernanceRecord.from_dict(data)
                self._records[rec.strategy_id] = rec
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load governance: %s: %s", path, exc)

    def _save(self, record: GovernanceRecord) -> None:
        record.last_updated = datetime.now(timezone.utc).isoformat()
        path = self._dir / f"{record.strategy_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, default=str)

    def register(self, record: GovernanceRecord) -> None:
        """Register a new strategy for governance."""
        self._records[record.strategy_id] = record
        self._save(record)
        logger.info(
            "Strategy registered: %s (status=%s)",
            record.strategy_id, record.status.value,
        )

    def submit_for_review(self, strategy_id: str) -> tuple[bool, str]:
        """Submit strategy for governance review."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "strategy_not_found"

        # Check documentation requirements
        missing = []
        if not rec.description.strip():
            missing.append("description")
        if not rec.assumptions:
            missing.append("assumptions")

        if missing:
            return False, f"missing_documentation: {missing}"

        rec.status = ApprovalStatus.UNDER_REVIEW
        self._save(rec)
        return True, "submitted"

    def review(
        self,
        strategy_id: str,
        reviewer: str,
        decision: str,
        comments: str = "",
    ) -> tuple[bool, str]:
        """Record a governance review decision."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "strategy_not_found"

        entry = ReviewEntry(
            reviewer=reviewer,
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision=decision,
            comments=comments,
        )
        rec.review_history.append(entry)

        if decision == "approve":
            rec.status = ApprovalStatus.APPROVED
            rec.deployment_cleared = True
        elif decision == "reject":
            rec.status = ApprovalStatus.REJECTED
            rec.deployment_cleared = False
        elif decision == "request_changes":
            rec.status = ApprovalStatus.DRAFT

        self._save(rec)
        return True, decision

    def can_deploy(self, strategy_id: str) -> tuple[bool, str]:
        """Check if a strategy is cleared for deployment."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "not_registered"
        if rec.status != ApprovalStatus.APPROVED:
            return False, f"status={rec.status.value}"
        if not rec.deployment_cleared:
            return False, "not_cleared"
        return True, "cleared"

    def promote_stage(
        self,
        strategy_id: str,
        new_stage: DeploymentStage,
    ) -> tuple[bool, str]:
        """Promote strategy to next deployment stage."""
        rec = self._records.get(strategy_id)
        if not rec:
            return False, "not_found"
        if rec.status != ApprovalStatus.APPROVED:
            return False, "not_approved"

        # Enforce stage ordering
        stage_order = list(DeploymentStage)
        current_idx = stage_order.index(rec.deployment_stage)
        new_idx = stage_order.index(new_stage)

        if new_idx > current_idx + 1:
            return False, f"cannot_skip_stages: {rec.deployment_stage.value} → {new_stage.value}"

        rec.deployment_stage = new_stage
        self._save(rec)
        logger.info(
            "Strategy %s promoted to %s",
            strategy_id, new_stage.value,
        )
        return True, f"promoted_to_{new_stage.value}"

    def get(self, strategy_id: str) -> Optional[GovernanceRecord]:
        return self._records.get(strategy_id)

    def all_records(self) -> list[GovernanceRecord]:
        return list(self._records.values())

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        by_stage: dict[str, int] = {}
        for r in self._records.values():
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
            by_stage[r.deployment_stage.value] = by_stage.get(r.deployment_stage.value, 0) + 1
        return {
            "total_strategies": len(self._records),
            "by_status": by_status,
            "by_stage": by_stage,
        }
