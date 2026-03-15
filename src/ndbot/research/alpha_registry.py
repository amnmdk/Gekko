"""
Alpha Signal Registry (Step 10).

Persistent registry of discovered alpha signals stored in
data/alpha_registry/ as JSON files. Each signal entry contains:

  - signal_id, description, model details
  - Sharpe ratio, hit rate, max drawdown
  - Robustness score (from edge stability testing)
  - Discovery date, last validation date
  - Status: CANDIDATE / VALIDATED / DEPLOYED / RETIRED

The registry enables tracking signal lifecycle from discovery
through production deployment.
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

DEFAULT_REGISTRY_DIR = "data/alpha_registry"


class SignalStatus(str, Enum):
    CANDIDATE = "CANDIDATE"      # Newly discovered, not validated
    VALIDATED = "VALIDATED"      # Passed stability testing
    DEPLOYED = "DEPLOYED"        # Active in paper/live trading
    RETIRED = "RETIRED"          # No longer active
    REJECTED = "REJECTED"        # Failed validation


@dataclass
class AlphaRegistryEntry:
    """A registered alpha signal."""
    signal_id: str
    name: str
    description: str
    model_type: str
    event_types: list[str]
    horizon: str
    status: SignalStatus = SignalStatus.CANDIDATE
    sharpe_ratio: float = 0.0
    hit_rate: float = 0.5
    max_drawdown_pct: float = 0.0
    mean_return_pct: float = 0.0
    t_statistic: float = 0.0
    p_value: float = 1.0
    robustness_score: float = 0.0
    n_observations: int = 0
    features_used: list[str] = field(default_factory=list)
    feature_importance: dict[str, float] = field(default_factory=dict)
    discovered_at: str = ""
    last_validated_at: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "name": self.name,
            "description": self.description,
            "model_type": self.model_type,
            "event_types": self.event_types,
            "horizon": self.horizon,
            "status": self.status.value,
            "sharpe_ratio": self.sharpe_ratio,
            "hit_rate": self.hit_rate,
            "max_drawdown_pct": self.max_drawdown_pct,
            "mean_return_pct": self.mean_return_pct,
            "t_statistic": self.t_statistic,
            "p_value": self.p_value,
            "robustness_score": self.robustness_score,
            "n_observations": self.n_observations,
            "features_used": self.features_used,
            "feature_importance": self.feature_importance,
            "discovered_at": self.discovered_at,
            "last_validated_at": self.last_validated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlphaRegistryEntry":
        d = dict(d)
        if "status" in d:
            d["status"] = SignalStatus(d["status"])
        return cls(**{
            k: d[k] for k in d
            if k in cls.__dataclass_fields__
        })


class AlphaRegistry:
    """
    Persistent registry for alpha signals.

    Stores signal metadata as individual JSON files under
    data/alpha_registry/{signal_id}.json
    """

    def __init__(self, registry_dir: str = DEFAULT_REGISTRY_DIR):
        self._dir = Path(registry_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, AlphaRegistryEntry] = {}
        self._load()

    def _load(self) -> None:
        """Load all entries from disk."""
        for path in self._dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                entry = AlphaRegistryEntry.from_dict(data)
                self._entries[entry.signal_id] = entry
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Failed to load %s: %s", path, exc)
        logger.debug("Loaded %d registry entries", len(self._entries))

    def register(self, entry: AlphaRegistryEntry) -> None:
        """Register or update an alpha signal."""
        self._entries[entry.signal_id] = entry
        self._save_entry(entry)
        logger.info(
            "Registered signal: %s (status=%s, Sharpe=%.3f)",
            entry.signal_id, entry.status.value, entry.sharpe_ratio,
        )

    def update_status(
        self,
        signal_id: str,
        status: SignalStatus,
        notes: str = "",
    ) -> bool:
        """Update the status of a registered signal."""
        entry = self._entries.get(signal_id)
        if not entry:
            return False
        entry.status = status
        if notes:
            entry.notes = notes
        entry.last_validated_at = datetime.now(timezone.utc).isoformat()
        self._save_entry(entry)
        return True

    def get(self, signal_id: str) -> Optional[AlphaRegistryEntry]:
        return self._entries.get(signal_id)

    def all_entries(self) -> list[AlphaRegistryEntry]:
        return list(self._entries.values())

    def by_status(self, status: SignalStatus) -> list[AlphaRegistryEntry]:
        return [e for e in self._entries.values() if e.status == status]

    def ranking(self) -> list[AlphaRegistryEntry]:
        """Return entries ranked by composite score."""
        scored = []
        for e in self._entries.values():
            if e.status == SignalStatus.REJECTED:
                continue
            composite = (
                0.4 * min(e.sharpe_ratio / 2.0, 1.0)
                + 0.2 * e.hit_rate
                + 0.2 * e.robustness_score
                + 0.2 * (1.0 - min(e.p_value, 1.0))
            )
            scored.append((composite, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored]

    def summary(self) -> dict:
        """Return registry summary statistics."""
        by_status: dict[str, int] = {}
        for e in self._entries.values():
            by_status[e.status.value] = (
                by_status.get(e.status.value, 0) + 1
            )
        return {
            "total_signals": len(self._entries),
            "by_status": by_status,
            "top_signals": [
                {
                    "id": e.signal_id,
                    "name": e.name,
                    "sharpe": e.sharpe_ratio,
                    "status": e.status.value,
                }
                for e in self.ranking()[:5]
            ],
        }

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._entries.values()]

    def _save_entry(self, entry: AlphaRegistryEntry) -> None:
        path = self._dir / f"{entry.signal_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry.to_dict(), f, indent=2, default=str)
