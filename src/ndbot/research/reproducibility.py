"""
Research Reproducibility System (Step 11).

Every experiment must be fully reproducible. This module captures
and verifies all artifacts needed for reproduction:

  1. Dataset snapshot   — hash of input data
  2. Code version       — git commit hash
  3. Parameters         — full config dump
  4. Random seeds       — all RNG seeds used
  5. Environment        — Python version, package versions
  6. Metrics            — full output metrics
  7. Execution log      — timestamped execution steps

Reproduction workflow:
  - Save: reproducibility.capture(experiment_id, config, seeds)
  - Verify: reproducibility.verify(experiment_id, new_metrics)
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ReproducibilityRecord:
    """Complete reproducibility artifact for an experiment."""
    experiment_id: str
    timestamp: str
    code_version: str
    python_version: str
    platform_info: str
    parameters: dict = field(default_factory=dict)
    random_seeds: dict[str, int] = field(default_factory=dict)
    data_hashes: dict[str, str] = field(default_factory=dict)
    package_versions: dict[str, str] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    execution_log: list[str] = field(default_factory=list)
    is_verified: bool = False
    verification_details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "timestamp": self.timestamp,
            "code_version": self.code_version,
            "python_version": self.python_version,
            "platform_info": self.platform_info,
            "parameters": self.parameters,
            "random_seeds": self.random_seeds,
            "data_hashes": self.data_hashes,
            "package_versions": self.package_versions,
            "metrics": self.metrics,
            "execution_log": self.execution_log,
            "is_verified": self.is_verified,
            "verification_details": self.verification_details,
        }


class ReproducibilityTracker:
    """
    Captures and verifies experiment reproducibility.

    Usage:
        tracker = ReproducibilityTracker()
        record = tracker.capture(
            experiment_id="exp_001",
            config={"param1": 0.5},
            seeds={"main": 42, "bootstrap": 123},
            data={"candles": candle_array, "events": event_list},
        )
        # Later...
        is_repro, details = tracker.verify("exp_001", new_metrics)
    """

    def __init__(self, storage_dir: str = "data/reproducibility"):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def capture(
        self,
        experiment_id: str,
        config: dict,
        seeds: Optional[dict[str, int]] = None,
        data: Optional[dict[str, Any]] = None,
        metrics: Optional[dict] = None,
    ) -> ReproducibilityRecord:
        """
        Capture full reproducibility artifacts for an experiment.

        Parameters
        ----------
        config : dict
            Full parameter configuration.
        seeds : dict, optional
            RNG seeds used (e.g., {"main": 42}).
        data : dict, optional
            Input datasets to hash for integrity verification.
        metrics : dict, optional
            Output metrics to record.
        """
        record = ReproducibilityRecord(
            experiment_id=experiment_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            code_version=self._get_git_hash(),
            python_version=sys.version,
            platform_info=platform.platform(),
            parameters=config,
            random_seeds=seeds or {},
            package_versions=self._get_package_versions(),
            metrics=metrics or {},
        )

        # Hash input data
        if data:
            for name, dataset in data.items():
                record.data_hashes[name] = self._hash_data(dataset)

        # Save record
        self._save(record)

        record.execution_log.append(
            f"Captured at {record.timestamp} "
            f"(git={record.code_version[:8]})"
        )

        logger.info(
            "Reproducibility captured: %s (git=%s, seeds=%s)",
            experiment_id, record.code_version[:8],
            record.random_seeds,
        )
        return record

    def verify(
        self,
        experiment_id: str,
        new_metrics: dict,
        tolerance: float = 1e-6,
    ) -> tuple[bool, dict]:
        """
        Verify that an experiment reproduces the original results.

        Parameters
        ----------
        new_metrics : dict
            Metrics from reproduction attempt.
        tolerance : float
            Acceptable numeric difference.

        Returns
        -------
        (is_reproduced, details)
        """
        record = self.load(experiment_id)
        if not record:
            return False, {"error": "record_not_found"}

        details: dict = {
            "metric_comparisons": {},
            "matches": 0,
            "mismatches": 0,
        }

        for key, original_val in record.metrics.items():
            new_val = new_metrics.get(key)
            if new_val is None:
                details["metric_comparisons"][key] = {
                    "status": "missing_in_new",
                    "original": original_val,
                }
                details["mismatches"] += 1
                continue

            if isinstance(original_val, (int, float)) and isinstance(new_val, (int, float)):
                diff = abs(original_val - new_val)
                match = diff <= tolerance
                details["metric_comparisons"][key] = {
                    "original": original_val,
                    "new": new_val,
                    "diff": round(diff, 10),
                    "match": match,
                }
                if match:
                    details["matches"] += 1
                else:
                    details["mismatches"] += 1
            else:
                match = original_val == new_val
                details["metric_comparisons"][key] = {
                    "original": original_val,
                    "new": new_val,
                    "match": match,
                }
                if match:
                    details["matches"] += 1
                else:
                    details["mismatches"] += 1

        total = details["matches"] + details["mismatches"]
        is_reproduced = details["mismatches"] == 0 and total > 0

        # Update record
        record.is_verified = is_reproduced
        record.verification_details = details
        self._save(record)

        return is_reproduced, details

    def verify_data_integrity(
        self,
        experiment_id: str,
        data: dict[str, Any],
    ) -> tuple[bool, dict]:
        """Verify that input data matches the original hashes."""
        record = self.load(experiment_id)
        if not record:
            return False, {"error": "record_not_found"}

        results: dict[str, dict] = {}
        all_match = True

        for name, dataset in data.items():
            current_hash = self._hash_data(dataset)
            original_hash = record.data_hashes.get(name)

            if original_hash is None:
                results[name] = {"status": "no_original_hash"}
                all_match = False
            elif current_hash == original_hash:
                results[name] = {
                    "status": "match",
                    "hash": current_hash,
                }
            else:
                results[name] = {
                    "status": "mismatch",
                    "original": original_hash,
                    "current": current_hash,
                }
                all_match = False

        return all_match, results

    def load(self, experiment_id: str) -> Optional[ReproducibilityRecord]:
        """Load a reproducibility record."""
        path = self._dir / f"{experiment_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return ReproducibilityRecord(**{
            k: data[k] for k in data
            if k in ReproducibilityRecord.__dataclass_fields__
        })

    def list_records(self, limit: int = 50) -> list[dict]:
        """List all reproducibility records."""
        records = []
        for path in sorted(self._dir.glob("*.json"), reverse=True):
            with open(path, encoding="utf-8") as f:
                records.append(json.load(f))
            if len(records) >= limit:
                break
        return records

    def _save(self, record: ReproducibilityRecord) -> None:
        path = self._dir / f"{record.experiment_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2, default=str)

    @staticmethod
    def _get_git_hash() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()[:12] if result.returncode == 0 else "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "unknown"

    @staticmethod
    def _get_package_versions() -> dict[str, str]:
        """Get versions of key packages."""
        versions = {}
        for pkg in ["numpy", "pandas", "scipy", "sklearn", "fastapi", "pydantic"]:
            try:
                mod = __import__(pkg)
                versions[pkg] = getattr(mod, "__version__", "unknown")
            except ImportError:
                pass
        return versions

    @staticmethod
    def _hash_data(data: Any) -> str:
        """Compute deterministic hash of data."""
        if isinstance(data, np.ndarray):
            raw = data.tobytes()
        elif isinstance(data, (list, dict)):
            raw = json.dumps(data, sort_keys=True, default=str).encode()
        elif isinstance(data, str):
            raw = data.encode()
        elif isinstance(data, bytes):
            raw = data
        else:
            raw = str(data).encode()
        return hashlib.sha256(raw).hexdigest()[:16]
