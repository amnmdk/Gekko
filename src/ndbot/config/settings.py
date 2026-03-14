"""
Configuration schema — validated by Pydantic v2.
All monetary values in USD, all durations in seconds unless noted.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Feed configuration
# ---------------------------------------------------------------------------

class FeedConfig(BaseModel):
    name: str
    url: str
    domain: Literal["ENERGY_GEO", "AI_RELEASES"]
    poll_interval_seconds: int = Field(default=60, ge=10)
    enabled: bool = True
    credibility_weight: float = Field(default=1.0, ge=0.0, le=2.0)


# ---------------------------------------------------------------------------
# Signal configuration
# ---------------------------------------------------------------------------

class SignalConfig(BaseModel):
    domain: Literal["ENERGY_GEO", "AI_RELEASES"]
    enabled: bool = True
    # Minimum confidence score [0,1] required to emit a signal
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)
    # Expected holding period in minutes
    holding_minutes: int = Field(default=60, ge=1)
    # Risk per trade as fraction of equity
    risk_per_trade: float = Field(default=0.01, ge=0.001, le=0.1)
    # Take-profit / stop-loss ratio
    rr_ratio: float = Field(default=2.0, ge=0.5)


# ---------------------------------------------------------------------------
# Market data configuration
# ---------------------------------------------------------------------------

class MarketConfig(BaseModel):
    # Symbol traded on the exchange (e.g. "BTC/USDT")
    symbol: str = "BTC/USDT"
    # Timeframe for intraday candles
    timeframe: str = "5m"
    # How many candles to maintain in memory
    candle_window: int = Field(default=200, ge=50)
    # ATR window for regime detection
    atr_period: int = Field(default=14, ge=5)
    # Rolling window for ATR percentile (candles)
    atr_percentile_window: int = Field(default=100, ge=30)
    # Short / long MA for trend regime
    ma_short: int = Field(default=20, ge=5)
    ma_long: int = Field(default=50, ge=10)


# ---------------------------------------------------------------------------
# Portfolio / risk configuration
# ---------------------------------------------------------------------------

class PortfolioConfig(BaseModel):
    initial_capital: float = Field(default=100.0, ge=1.0)
    currency: str = "USD"
    max_concurrent_positions: int = Field(default=3, ge=1)
    max_daily_loss_pct: float = Field(default=0.05, ge=0.001, le=0.5)
    max_drawdown_pct: float = Field(default=0.15, ge=0.01, le=0.9)
    # Time-based stop: exit if position open longer than this many minutes
    time_stop_minutes: int = Field(default=240, ge=5)
    # Commission rate per side
    commission_rate: float = Field(default=0.001, ge=0.0, le=0.05)
    # Slippage rate per side (simulate mode)
    slippage_rate: float = Field(default=0.0005, ge=0.0, le=0.01)


# ---------------------------------------------------------------------------
# Confirmation engine configuration
# ---------------------------------------------------------------------------

class ConfirmationConfig(BaseModel):
    enabled: bool = True
    # Breakout: price must exceed recent high by this fraction
    breakout_threshold: float = Field(default=0.002, ge=0.0, le=0.05)
    # Volume spike: volume must exceed N-period average by this multiplier
    volume_spike_multiplier: float = Field(default=1.5, ge=1.0)
    # Volatility expansion: ATR must exceed recent average by this multiplier
    volatility_expansion_multiplier: float = Field(default=1.3, ge=1.0)
    # Lookback candles for breakout / volume / volatility reference
    lookback_candles: int = Field(default=20, ge=5)


# ---------------------------------------------------------------------------
# Storage configuration
# ---------------------------------------------------------------------------

class StorageConfig(BaseModel):
    db_path: str = "data/ndbot.db"
    events_retention_days: int = Field(default=365, ge=1)


# ---------------------------------------------------------------------------
# Paper trading configuration
# ---------------------------------------------------------------------------

class PaperConfig(BaseModel):
    exchange_id: str = "binance"
    # Force dry-run; refuse execution if sandbox not available
    dry_run: bool = True
    # Explicitly require sandbox/testnet
    require_sandbox: bool = True
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


# ---------------------------------------------------------------------------
# Research configuration
# ---------------------------------------------------------------------------

class ResearchConfig(BaseModel):
    # Event study window: candles before/after event
    pre_event_candles: int = Field(default=12, ge=1)
    post_event_candles: int = Field(default=48, ge=1)
    # Walk-forward: training and test window in days
    train_days: int = Field(default=365 * 3, ge=30)
    test_days: int = Field(default=365, ge=7)
    # Step size for walk-forward rolls (days)
    step_days: int = Field(default=90, ge=7)


# ---------------------------------------------------------------------------
# Top-level bot configuration
# ---------------------------------------------------------------------------

class BotConfig(BaseModel):
    # Human-readable run label
    run_name: str = "ndbot-run"
    mode: Literal["simulate", "backtest", "paper"] = "simulate"
    log_level: str = "INFO"

    feeds: list[FeedConfig] = Field(default_factory=list)
    signals: list[SignalConfig] = Field(default_factory=list)
    market: MarketConfig = Field(default_factory=MarketConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    confirmation: ConfirmationConfig = Field(default_factory=ConfirmationConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    # Arbitrary extra fields (e.g. for extensions)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        allowed = {"simulate", "backtest", "paper"}
        if v not in allowed:
            raise ValueError(f"mode must be one of {allowed}")
        return v

    @model_validator(mode="after")
    def _validate_paper_safety(self) -> "BotConfig":
        if self.mode == "paper" and not self.paper.dry_run:
            # Warn but allow — user must be explicit in config
            import warnings
            warnings.warn(
                "PAPER MODE: dry_run is False. REAL ORDERS may be submitted. "
                "Ensure exchange sandbox is configured.",
                stacklevel=2,
            )
        return self
