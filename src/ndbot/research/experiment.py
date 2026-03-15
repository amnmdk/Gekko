"""
Experiment tracking system.

Each run records:
  - Timestamp
  - Full parameter set
  - Config hash (for deduplication)
  - Git commit hash
  - All performance metrics
  - Equity curve snapshot

Results stored in SQLite for querying and comparison.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ExperimentTracker:
    """
    Track and compare experiment runs.

    Usage:
        tracker = ExperimentTracker()
        exp_id = tracker.start("my-experiment", config_dict)
        # ... run strategy ...
        tracker.finish(exp_id, metrics_dict, equity_curve, trade_log)
    """

    def __init__(self, results_dir: str = "results") -> None:
        self._results_dir = Path(results_dir)
        self._results_dir.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, dict] = {}

    def start(
        self,
        name: str,
        config: dict,
        tags: Optional[list[str]] = None,
    ) -> str:
        """
        Start a new experiment. Returns experiment_id.
        """
        timestamp = datetime.now(timezone.utc)
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        config_hash = self._hash_config(config)
        git_hash = self._get_git_hash()
        exp_id = f"{name}_{ts_str}_{config_hash[:8]}"

        run_dir = self._results_dir / f"run_{exp_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        metadata = {
            "experiment_id": exp_id,
            "name": name,
            "timestamp": timestamp.isoformat(),
            "config_hash": config_hash,
            "git_commit": git_hash,
            "tags": tags or [],
            "status": "running",
        }

        # Save config snapshot
        config_path = run_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2, default=str)

        # Save metadata
        meta_path = run_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        self._active[exp_id] = {
            "run_dir": run_dir,
            "metadata": metadata,
            "start_time": timestamp,
        }

        logger.info(
            "Experiment started: %s (config=%s, git=%s)",
            exp_id, config_hash[:8], git_hash[:8],
        )
        return exp_id

    def finish(
        self,
        experiment_id: str,
        metrics: dict,
        equity_curve: Optional[list[float]] = None,
        trade_log: Optional[list[dict]] = None,
    ) -> str:
        """
        Finalise an experiment with results.
        Returns the path to the run directory.
        """
        if experiment_id not in self._active:
            # Reconstruct run dir from ID
            run_dir = self._results_dir / f"run_{experiment_id}"
            run_dir.mkdir(parents=True, exist_ok=True)
        else:
            run_dir = self._active[experiment_id]["run_dir"]

        end_time = datetime.now(timezone.utc)

        # Save metrics
        metrics_path = run_dir / "metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        # Save equity curve
        if equity_curve:
            eq_path = run_dir / "equity_curve.json"
            with open(eq_path, "w") as f:
                json.dump(equity_curve, f)

        # Save trade log
        if trade_log:
            trades_path = run_dir / "trade_log.json"
            with open(trades_path, "w") as f:
                json.dump(trade_log, f, indent=2, default=str)

        # Update metadata
        meta_path = run_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)
        else:
            metadata = {"experiment_id": experiment_id}

        metadata["status"] = "completed"
        metadata["end_time"] = end_time.isoformat()
        metadata["duration_seconds"] = (
            (end_time - self._active[experiment_id]["start_time"]).total_seconds()
            if experiment_id in self._active else 0
        )
        metadata["summary_metrics"] = {
            k: round(v, 6) if isinstance(v, float) else v
            for k, v in metrics.items()
            if isinstance(v, (int, float, str, bool))
        }

        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        if experiment_id in self._active:
            del self._active[experiment_id]

        logger.info("Experiment completed: %s → %s", experiment_id, run_dir)
        return str(run_dir)

    def list_experiments(self, limit: int = 50) -> list[dict]:
        """List all tracked experiments, most recent first."""
        experiments = []
        for d in sorted(self._results_dir.iterdir(), reverse=True):
            if not d.is_dir() or not d.name.startswith("run_"):
                continue
            meta_path = d / "metadata.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    experiments.append(json.load(f))
            if len(experiments) >= limit:
                break
        return experiments

    def load_experiment(self, experiment_id: str) -> Optional[dict]:
        """Load full experiment data."""
        run_dir = self._results_dir / f"run_{experiment_id}"
        if not run_dir.exists():
            return None

        result: dict[str, Any] = {}
        for fname in ["metadata.json", "config.json", "metrics.json"]:
            fpath = run_dir / fname
            if fpath.exists():
                with open(fpath) as f:
                    result[fname.replace(".json", "")] = json.load(f)

        eq_path = run_dir / "equity_curve.json"
        if eq_path.exists():
            with open(eq_path) as f:
                result["equity_curve"] = json.load(f)

        return result

    @staticmethod
    def _hash_config(config: dict) -> str:
        """Deterministic hash of config for experiment dedup."""
        serialised = json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()

    @staticmethod
    def _get_git_hash() -> str:
        """Get current git commit hash, or 'unknown'."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip()[:12] if result.returncode == 0 else "unknown"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "unknown"
