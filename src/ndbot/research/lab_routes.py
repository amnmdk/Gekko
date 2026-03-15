"""
Research Lab Dashboard API Routes (Step 12).

Extends the API with research lab visualisation endpoints:
  - Alpha pipeline status and signal rankings
  - Causal event analysis results
  - Regime classification state
  - Portfolio optimisation results
  - Edge decay monitoring
  - Multi-agent simulation summaries
  - Model comparison reports
"""
from __future__ import annotations

import logging

import numpy as np
from fastapi import APIRouter

logger = logging.getLogger(__name__)

lab_router = APIRouter(prefix="/lab", tags=["research_lab"])

# Lazy-loaded module references
_corpus = None
_embedding_engine = None
_causal_engine = None
_microstructure_engine = None
_signal_engine = None
_meta_engine = None
_optimizer = None
_regime_engine = None
_edge_monitor = None
_impact_model = None
_simulator = None


def init_lab_routes() -> None:
    """Initialise research lab route dependencies."""
    global _corpus, _embedding_engine, _causal_engine
    global _microstructure_engine, _signal_engine, _meta_engine
    global _optimizer, _regime_engine, _edge_monitor
    global _impact_model, _simulator

    try:
        from ..data.news_corpus import NewsCorpus
        _corpus = NewsCorpus()
    except Exception:
        pass

    try:
        from ..features.event_embeddings import EventEmbeddingEngine
        _embedding_engine = EventEmbeddingEngine()
    except Exception:
        pass

    try:
        from .causal_analysis import CausalAnalysisEngine
        _causal_engine = CausalAnalysisEngine()
    except Exception:
        pass

    try:
        from ..features.market_microstructure import MarketMicrostructureEngine
        _microstructure_engine = MarketMicrostructureEngine()
    except Exception:
        pass

    try:
        from .signal_models import SignalModelEngine
        _signal_engine = SignalModelEngine()
    except Exception:
        pass

    try:
        from ..portfolio.meta_strategy import MetaStrategyEngine
        _meta_engine = MetaStrategyEngine()
    except Exception:
        pass

    try:
        from ..portfolio.optimizer import PortfolioOptimizer
        _optimizer = PortfolioOptimizer()
    except Exception:
        pass

    try:
        from ..portfolio.regime_strategy import RegimeStrategyEngine
        _regime_engine = RegimeStrategyEngine()
    except Exception:
        pass

    try:
        from .edge_decay import EdgeDecayMonitor
        _edge_monitor = EdgeDecayMonitor()
    except Exception:
        pass

    try:
        from ..execution.impact_model import MarketImpactModel
        _impact_model = MarketImpactModel()
    except Exception:
        pass

    try:
        from ..simulation.market_simulator import MarketSimulator
        _simulator = MarketSimulator()
    except Exception:
        pass

    logger.info("Research lab routes initialised")


@lab_router.get("/status")
async def lab_status() -> dict:
    """Research lab module availability status."""
    return {
        "modules": {
            "news_corpus": _corpus is not None,
            "event_embeddings": _embedding_engine is not None,
            "causal_analysis": _causal_engine is not None,
            "market_microstructure": _microstructure_engine is not None,
            "signal_models": _signal_engine is not None,
            "meta_strategy": _meta_engine is not None,
            "portfolio_optimizer": _optimizer is not None,
            "regime_strategy": _regime_engine is not None,
            "edge_decay": _edge_monitor is not None,
            "impact_model": _impact_model is not None,
            "market_simulator": _simulator is not None,
        },
    }


@lab_router.get("/corpus/stats")
async def corpus_stats() -> dict:
    """News corpus statistics."""
    if not _corpus:
        return {"error": "corpus_not_loaded"}
    stats = _corpus.compute_stats()
    return stats.to_dict()


@lab_router.get("/regime")
async def current_regime() -> dict:
    """Current regime classification (demo data)."""
    if not _regime_engine:
        return {"error": "regime_engine_not_loaded"}

    rng = np.random.default_rng(42)
    demo_returns = rng.normal(0.0003, 0.015, 200)
    demo_volumes = rng.lognormal(10, 1, 200)

    regime = _regime_engine.classify_regime(
        returns=demo_returns, volumes=demo_volumes,
    )
    adaptation = _regime_engine.get_adaptation(regime)

    return {
        "regime": regime.to_dict(),
        "adaptation": {
            "size_multiplier": adaptation.size_multiplier,
            "signal_threshold": adaptation.signal_threshold,
            "stop_distance_multiplier": adaptation.stop_distance_multiplier,
            "max_positions": adaptation.max_positions,
            "notes": adaptation.notes,
        },
    }


@lab_router.get("/edge-decay")
async def edge_decay_status() -> dict:
    """Edge decay status for demo signal."""
    if not _edge_monitor:
        return {"error": "edge_monitor_not_loaded"}

    rng = np.random.default_rng(42)
    # Simulate decaying signal
    n = 200
    base = rng.normal(0.001, 0.01, n)
    decay = np.linspace(1.0, 0.3, n)
    signal_returns = base * decay

    report = _edge_monitor.analyse(
        signal_id="demo_signal",
        signal_returns=signal_returns,
    )
    return report.to_dict()


@lab_router.get("/portfolio/optimize")
async def portfolio_optimize() -> dict:
    """Run portfolio optimisation comparison (demo data)."""
    if not _optimizer:
        return {"error": "optimizer_not_loaded"}

    rng = np.random.default_rng(42)
    n_obs = 252
    names = ["BTC", "ETH", "SOL", "AVAX", "MATIC"]

    returns = rng.multivariate_normal(
        mean=[0.001, 0.0008, 0.0012, 0.0006, 0.0009],
        cov=np.diag([0.04, 0.05, 0.06, 0.07, 0.05]) * 0.01,
        size=n_obs,
    )

    results = _optimizer.compare_methods(returns, names)
    return {
        "allocations": [a.to_dict() for a in results],
        "n_methods": len(results),
    }


@lab_router.get("/simulation/run")
async def run_simulation() -> dict:
    """Run a quick multi-agent simulation."""
    if not _simulator:
        return {"error": "simulator_not_loaded"}

    result = _simulator.run(
        n_steps=200,
        event_schedule=[(30, 0.02), (80, -0.03), (150, 0.015)],
    )
    return result.to_dict()


@lab_router.get("/models/compare")
async def compare_models() -> dict:
    """Run model comparison on demo data."""
    if not _signal_engine:
        return {"error": "signal_engine_not_loaded"}

    rng = np.random.default_rng(42)
    n = 500
    n_feat = 10
    features = rng.normal(0, 1, (n, n_feat))
    returns = (
        0.3 * features[:, 0]
        + 0.2 * features[:, 1]
        + rng.normal(0, 0.5, n)
    ) * 0.01

    names = [f"feature_{i}" for i in range(n_feat)]
    report = _signal_engine.train_and_compare(features, returns, names)
    return report.to_dict()
