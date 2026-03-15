"""
Feature engineering modules for event-driven alpha discovery.
"""
from .event_embeddings import EventEmbeddingEngine
from .market_microstructure import MarketMicrostructureEngine
from .news_features import NewsFeatureEngine

__all__ = [
    "NewsFeatureEngine",
    "EventEmbeddingEngine",
    "MarketMicrostructureEngine",
]
