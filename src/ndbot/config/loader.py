"""
YAML config loader with environment variable override support.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .settings import BotConfig


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (non-destructive copy)."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(path: str | Path) -> BotConfig:
    """
    Load BotConfig from *path* (YAML).

    Environment overrides are applied on top using the pattern:
        NDBOT__<SECTION>__<KEY>=value
    e.g. NDBOT__PORTFOLIO__INITIAL_CAPITAL=500
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    with p.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    # Apply environment overrides
    env_overrides = _collect_env_overrides()
    if env_overrides:
        raw = _deep_merge(raw, env_overrides)

    return BotConfig.model_validate(raw)


def _collect_env_overrides() -> dict[str, Any]:
    """
    Collect NDBOT__* env vars and convert to nested dict.
    E.g.  NDBOT__PORTFOLIO__INITIAL_CAPITAL=500
          → {"portfolio": {"initial_capital": 500}}
    """
    prefix = "NDBOT__"
    result: dict[str, Any] = {}
    for key, val in os.environ.items():
        if not key.upper().startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("__")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        # Attempt numeric / boolean coercions
        node[parts[-1]] = _coerce(val)
    return result


def _coerce(val: str) -> Any:
    """Best-effort coercion for env var strings."""
    if val.lower() in ("true", "yes", "1"):
        return True
    if val.lower() in ("false", "no", "0"):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val
