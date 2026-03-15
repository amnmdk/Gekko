"""
Alpha Discovery Dashboard API Routes (Step 12).

Provides REST endpoints for the dashboard to display:
  - Event frequency by type
  - Signal performance metrics
  - Alpha ranking
  - Pipeline run history
  - Taxonomy overview
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from ..data.news_dataset_builder import NewsDatasetBuilder
from .alpha_registry import AlphaRegistry, SignalStatus
from .event_taxonomy import EventTaxonomy

logger = logging.getLogger(__name__)

alpha_router = APIRouter(prefix="/alpha", tags=["alpha"])

_registry: AlphaRegistry | None = None
_taxonomy: EventTaxonomy | None = None
_dataset: NewsDatasetBuilder | None = None


def init_alpha_routes(
    registry: AlphaRegistry | None = None,
    taxonomy: EventTaxonomy | None = None,
    dataset: NewsDatasetBuilder | None = None,
) -> None:
    """Initialise alpha routes with shared state."""
    global _registry, _taxonomy, _dataset
    _registry = registry or AlphaRegistry()
    _taxonomy = taxonomy or EventTaxonomy()
    _dataset = dataset or NewsDatasetBuilder()


def _get_registry() -> AlphaRegistry:
    if _registry is None:
        init_alpha_routes()
    return _registry  # type: ignore[return-value]


def _get_taxonomy() -> EventTaxonomy:
    if _taxonomy is None:
        init_alpha_routes()
    return _taxonomy  # type: ignore[return-value]


def _get_dataset() -> NewsDatasetBuilder:
    if _dataset is None:
        init_alpha_routes()
    return _dataset  # type: ignore[return-value]


@alpha_router.get("/taxonomy")
async def get_taxonomy() -> list[dict]:
    """Return full event taxonomy."""
    return _get_taxonomy().to_list()


@alpha_router.get("/event-counts")
async def get_event_counts() -> dict[str, Any]:
    """Return event counts by type from the dataset."""
    dataset = _get_dataset()
    counts = dataset.get_event_types()
    return {
        "total_events": dataset.total_events(),
        "by_type": counts,
    }


@alpha_router.get("/signals")
async def get_signals(
    status: str | None = Query(default=None),
) -> list[dict]:
    """Return registered alpha signals, optionally filtered by status."""
    registry = _get_registry()
    if status:
        try:
            s = SignalStatus(status.upper())
            entries = registry.by_status(s)
        except ValueError:
            entries = registry.all_entries()
    else:
        entries = registry.all_entries()
    return [e.to_dict() for e in entries]


@alpha_router.get("/signals/ranking")
async def get_signal_ranking() -> list[dict]:
    """Return signals ranked by composite score."""
    registry = _get_registry()
    ranked = registry.ranking()
    return [e.to_dict() for e in ranked]


@alpha_router.get("/signals/{signal_id}")
async def get_signal(signal_id: str) -> dict:
    """Return details of a specific signal."""
    entry = _get_registry().get(signal_id)
    if not entry:
        return {"error": "Signal not found"}
    return entry.to_dict()


@alpha_router.get("/registry/summary")
async def get_registry_summary() -> dict:
    """Return registry summary statistics."""
    return _get_registry().summary()


@alpha_router.get("/dataset/stats")
async def get_dataset_stats() -> dict[str, Any]:
    """Return dataset statistics."""
    dataset = _get_dataset()
    return {
        "total_events": dataset.total_events(),
        "event_types": dataset.get_event_types(),
        "storage_stats": dataset.stats,
    }
