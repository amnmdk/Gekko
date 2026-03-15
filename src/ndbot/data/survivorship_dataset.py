"""
Survivorship-Bias Free Dataset (Step 2).

Maintains historically accurate asset membership records so that
backtests use only assets that were available at each point in time.

Features:
  - Historical index/universe membership with entry/exit dates
  - Delisted asset retention with delisting reason
  - Asset lifecycle tracking (listed, active, suspended, delisted)
  - Point-in-time universe reconstruction
  - Survivorship bias detection in existing datasets
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


class AssetLifecycle(str, Enum):
    LISTED = "LISTED"          # Newly listed, not yet tradeable
    ACTIVE = "ACTIVE"          # Currently tradeable
    SUSPENDED = "SUSPENDED"    # Temporarily halted
    DELISTED = "DELISTED"      # Permanently removed


@dataclass
class AssetRecord:
    """Historical record of an asset's lifecycle."""
    symbol: str
    name: str = ""
    asset_class: str = "CRYPTO"
    exchange: str = ""
    listed_at: Optional[str] = None
    delisted_at: Optional[str] = None
    lifecycle: AssetLifecycle = AssetLifecycle.ACTIVE
    delisting_reason: str = ""
    metadata: dict = field(default_factory=dict)

    def is_active_at(self, dt: datetime) -> bool:
        """Check if asset was active at a given datetime."""
        if self.listed_at:
            listed = datetime.fromisoformat(self.listed_at)
            if listed.tzinfo is None:
                listed = listed.replace(tzinfo=timezone.utc)
            if dt < listed:
                return False
        if self.delisted_at:
            delisted = datetime.fromisoformat(self.delisted_at)
            if delisted.tzinfo is None:
                delisted = delisted.replace(tzinfo=timezone.utc)
            if dt >= delisted:
                return False
        return self.lifecycle in (
            AssetLifecycle.ACTIVE, AssetLifecycle.LISTED,
        )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "asset_class": self.asset_class,
            "exchange": self.exchange,
            "listed_at": self.listed_at,
            "delisted_at": self.delisted_at,
            "lifecycle": self.lifecycle.value,
            "delisting_reason": self.delisting_reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AssetRecord":
        d = dict(d)
        if "lifecycle" in d:
            d["lifecycle"] = AssetLifecycle(d["lifecycle"])
        return cls(**{
            k: d[k] for k in d if k in cls.__dataclass_fields__
        })


@dataclass
class MembershipChange:
    """Records when an asset enters or exits an index/universe."""
    symbol: str
    index_name: str
    action: str  # "ADD" or "REMOVE"
    effective_date: str
    reason: str = ""


class SurvivorshipFreeDataset:
    """
    Maintains survivorship-bias-free asset datasets.

    Stores full history of:
      - Asset listings and delistings
      - Index membership changes
      - Asset lifecycle transitions

    Enables point-in-time universe reconstruction for any
    historical date.
    """

    def __init__(self, storage_dir: str = "data/survivorship"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._assets: dict[str, AssetRecord] = {}
        self._membership_log: list[MembershipChange] = []
        self._load()

    def _load(self) -> None:
        """Load existing records from disk."""
        assets_path = self._dir / "assets.json"
        if assets_path.exists():
            with open(assets_path, encoding="utf-8") as f:
                data = json.load(f)
            for d in data:
                rec = AssetRecord.from_dict(d)
                self._assets[rec.symbol] = rec

        log_path = self._dir / "membership_log.json"
        if log_path.exists():
            with open(log_path, encoding="utf-8") as f:
                entries = json.load(f)
            for entry in entries:
                self._membership_log.append(MembershipChange(**entry))

        logger.debug(
            "Loaded %d assets, %d membership changes",
            len(self._assets), len(self._membership_log),
        )

    def _save(self) -> None:
        """Persist records to disk."""
        assets_path = self._dir / "assets.json"
        with open(assets_path, "w", encoding="utf-8") as f:
            json.dump(
                [a.to_dict() for a in self._assets.values()],
                f, indent=2,
            )

        log_path = self._dir / "membership_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "symbol": m.symbol,
                        "index_name": m.index_name,
                        "action": m.action,
                        "effective_date": m.effective_date,
                        "reason": m.reason,
                    }
                    for m in self._membership_log
                ],
                f, indent=2,
            )

    def add_asset(self, record: AssetRecord) -> None:
        """Add or update an asset record."""
        self._assets[record.symbol] = record
        self._save()
        logger.info("Asset added: %s (%s)", record.symbol, record.lifecycle.value)

    def delist_asset(
        self,
        symbol: str,
        delisted_at: Optional[str] = None,
        reason: str = "",
    ) -> bool:
        """Mark an asset as delisted."""
        rec = self._assets.get(symbol)
        if not rec:
            return False
        rec.lifecycle = AssetLifecycle.DELISTED
        rec.delisted_at = delisted_at or datetime.now(timezone.utc).isoformat()
        rec.delisting_reason = reason
        self._save()
        logger.info("Asset delisted: %s reason=%s", symbol, reason)
        return True

    def record_membership_change(self, change: MembershipChange) -> None:
        """Record an index membership change."""
        self._membership_log.append(change)
        self._save()

    def get_universe_at(self, dt: datetime) -> list[AssetRecord]:
        """
        Reconstruct the asset universe at a given point in time.
        Returns only assets that were active at that datetime.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return [
            a for a in self._assets.values()
            if a.is_active_at(dt)
        ]

    def get_index_members_at(
        self, index_name: str, dt: datetime,
    ) -> list[str]:
        """Get members of a specific index at a point in time."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        members: set[str] = set()
        dt_str = dt.isoformat()

        for change in self._membership_log:
            if (change.index_name == index_name
                    and change.effective_date <= dt_str):
                if change.action == "ADD":
                    members.add(change.symbol)
                elif change.action == "REMOVE":
                    members.discard(change.symbol)

        return sorted(members)

    def detect_survivorship_bias(
        self,
        symbols: list[str],
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """
        Check if a symbol list suffers from survivorship bias.

        Compares the provided list against the historically accurate
        universe to identify assets that were not available
        throughout the entire period.
        """
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        issues: list[dict] = []
        clean_symbols: list[str] = []

        for sym in symbols:
            rec = self._assets.get(sym)
            if not rec:
                issues.append({
                    "symbol": sym,
                    "issue": "not_in_dataset",
                    "severity": "warning",
                })
                clean_symbols.append(sym)
                continue

            if not rec.is_active_at(start_date):
                issues.append({
                    "symbol": sym,
                    "issue": "not_listed_at_start",
                    "listed_at": rec.listed_at,
                    "severity": "critical",
                })
            elif not rec.is_active_at(end_date):
                issues.append({
                    "symbol": sym,
                    "issue": "delisted_before_end",
                    "delisted_at": rec.delisted_at,
                    "reason": rec.delisting_reason,
                    "severity": "critical",
                })
            else:
                clean_symbols.append(sym)

        bias_score = (
            len(issues) / max(1, len(symbols))
        )
        return {
            "total_symbols": len(symbols),
            "clean_symbols": len(clean_symbols),
            "issues": issues,
            "bias_score": round(bias_score, 4),
            "has_survivorship_bias": len(issues) > 0,
        }

    @property
    def all_assets(self) -> list[AssetRecord]:
        return list(self._assets.values())

    @property
    def delisted_assets(self) -> list[AssetRecord]:
        return [
            a for a in self._assets.values()
            if a.lifecycle == AssetLifecycle.DELISTED
        ]

    @property
    def active_assets(self) -> list[AssetRecord]:
        return [
            a for a in self._assets.values()
            if a.lifecycle == AssetLifecycle.ACTIVE
        ]

    def summary(self) -> dict:
        by_lifecycle: dict[str, int] = {}
        for a in self._assets.values():
            by_lifecycle[a.lifecycle.value] = (
                by_lifecycle.get(a.lifecycle.value, 0) + 1
            )
        return {
            "total_assets": len(self._assets),
            "by_lifecycle": by_lifecycle,
            "membership_changes": len(self._membership_log),
        }
