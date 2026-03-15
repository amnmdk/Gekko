"""
Walk-Forward Validation

Methodology
-----------
Rolling expanding or anchored walk-forward:
  - Train window: 3 years of data
  - Test window: 1 year of data
  - Roll step: configurable (default 90 days)

For each window:
  1. Identify events in the TRAIN period
  2. Optimise signal parameters (min_confidence, risk_per_trade)
     using grid search over a performance metric (Sharpe ratio)
  3. Apply optimised parameters to the TEST period
  4. Record out-of-sample performance metrics

Outputs
-------
  - results/walkforward_{run_name}_{timestamp}.json  — per-window metrics
  - results/walkforward_{run_name}_{timestamp}.csv   — summary table
  - results/walkforward_{run_name}_{timestamp}.png   — equity curves

Scientific notes
----------------
In-sample optimisation with out-of-sample evaluation is a minimal standard.
Multiple testing correction is not applied here. Treat Sharpe > 0.5 OOS
as suggestive, not conclusive. Statistical significance requires >30 OOS trades.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..portfolio.metrics import PortfolioMetrics
from ..signals.confidence_model import ConfidenceModel

logger = logging.getLogger(__name__)


# Parameter grid to search over
_PARAM_GRID = {
    "min_confidence": [0.35, 0.45, 0.55, 0.65],
    "risk_per_trade": [0.005, 0.01, 0.015, 0.02],
}

# Backtest constants
_ATR_STOP_MULTIPLIER = 1.5        # Stop distance = ATR × this
_ATR_LOOKBACK = 14                # Candles to compute ATR over
_MIN_ATR_CANDLES = 5              # Minimum candles needed for ATR
_EXIT_CANDLES = 12                # Exit after N candles (1h at 5m)
_FALLBACK_STOP_FRACTION = 0.01   # Fallback stop as fraction of entry price


class WalkForwardValidator:
    """
    Walk-forward validation engine.

    Parameters
    ----------
    events: list[dict]
        Historical events (with 'published_at', 'sentiment_score', etc.)
    candles: pd.DataFrame
        OHLCV candle history (datetime index, UTC).
    train_days: int
        Training window length in days.
    test_days: int
        Out-of-sample test window length in days.
    step_days: int
        Roll step in days.
    initial_capital: float
        Starting equity for each window.
    timeframe_minutes: int
        Candle duration in minutes.
    """

    def __init__(
        self,
        events: list[dict],
        candles: pd.DataFrame,
        train_days: int = 365 * 3,
        test_days: int = 365,
        step_days: int = 90,
        initial_capital: float = 100.0,
        timeframe_minutes: int = 5,
        commission_rate: float = 0.001,
    ):
        self._events = sorted(events, key=lambda e: e.get("published_at", ""))
        self._candles = candles.sort_index()
        self._train_days = train_days
        self._test_days = test_days
        self._step_days = step_days
        self._initial_capital = initial_capital
        self._tf_min = timeframe_minutes
        self._commission = commission_rate

    def run(self, output_dir: str = "results", run_name: str = "walkforward") -> dict:
        """
        Execute the full walk-forward validation.
        Returns a dict with window-level results and aggregate statistics.
        """
        results_dir = Path(output_dir)
        results_dir.mkdir(parents=True, exist_ok=True)

        windows = self._build_windows()
        if not windows:
            return {"error": "insufficient_data_for_windows"}

        logger.info("Walk-forward: %d windows to evaluate", len(windows))
        window_results = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(windows):
            logger.info(
                "Window %d/%d — TRAIN: %s → %s | TEST: %s → %s",
                i + 1, len(windows),
                train_start.date(), train_end.date(),
                test_start.date(), test_end.date(),
            )
            result = self._evaluate_window(
                train_start, train_end, test_start, test_end, window_idx=i
            )
            window_results.append(result)

        # Aggregate OOS metrics
        agg = self._aggregate_windows(window_results)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        base_name = f"walkforward_{run_name}_{timestamp}"
        report = {
            "run_name": run_name,
            "timestamp": timestamp,
            "n_windows": len(window_results),
            "train_days": self._train_days,
            "test_days": self._test_days,
            "step_days": self._step_days,
            "aggregate_oos": agg,
            "windows": window_results,
        }

        # Save JSON
        json_path = results_dir / f"{base_name}.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Walk-forward JSON saved: %s", json_path)

        # Save CSV summary
        df = pd.DataFrame([
            {
                "window": w["window_idx"],
                "test_start": w["test_start"],
                "test_end": w["test_end"],
                "oos_trades": w["oos"]["total_trades"],
                "oos_sharpe": w["oos"].get("sharpe_ratio", 0.0),
                "oos_return_pct": w["oos"].get("total_return_pct", 0.0),
                "oos_max_dd": w["oos"].get("max_drawdown_pct", 0.0),
                "best_conf": w.get("best_params", {}).get("min_confidence", "N/A"),
                "best_risk": w.get("best_params", {}).get("risk_per_trade", "N/A"),
            }
            for w in window_results
        ])
        csv_path = results_dir / f"{base_name}.csv"
        df.to_csv(csv_path, index=False)
        logger.info("Walk-forward CSV saved: %s", csv_path)

        # Plot
        plot_path = results_dir / f"{base_name}.png"
        self._plot_equity_curves(window_results, plot_path, run_name)

        return report

    # ------------------------------------------------------------------
    # Window construction
    # ------------------------------------------------------------------

    def _build_windows(self) -> list[tuple]:
        """Generate (train_start, train_end, test_start, test_end) tuples."""
        if len(self._candles) == 0:
            return []
        first_ts = self._candles.index[0].to_pydatetime().replace(tzinfo=timezone.utc)
        last_ts = self._candles.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)

        windows = []
        step = timedelta(days=self._step_days)
        train_start = first_ts

        while True:
            train_end = train_start + timedelta(days=self._train_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self._test_days)
            if test_end > last_ts:
                break
            windows.append((train_start, train_end, test_start, test_end))
            train_start += step

        return windows

    # ------------------------------------------------------------------
    # Per-window evaluation
    # ------------------------------------------------------------------

    def _evaluate_window(
        self,
        train_start: datetime,
        train_end: datetime,
        test_start: datetime,
        test_end: datetime,
        window_idx: int,
    ) -> dict:
        # Split events and candles
        train_events = self._filter_events(train_start, train_end)
        test_events = self._filter_events(test_start, test_end)
        train_candles = self._filter_candles(train_start, train_end)
        test_candles = self._filter_candles(test_start, test_end)

        # --- In-sample optimisation ---
        best_params, is_metrics = self._optimise(train_events, train_candles)

        # --- Out-of-sample evaluation ---
        oos_metrics = self._backtest_simple(test_events, test_candles, best_params)

        return {
            "window_idx": window_idx,
            "train_start": str(train_start.date()),
            "train_end": str(train_end.date()),
            "test_start": str(test_start.date()),
            "test_end": str(test_end.date()),
            "n_train_events": len(train_events),
            "n_test_events": len(test_events),
            "best_params": best_params,
            "in_sample": is_metrics,
            "oos": oos_metrics,
        }

    def _optimise(
        self, events: list[dict], candles: pd.DataFrame
    ) -> tuple[dict, dict]:
        """Grid search over _PARAM_GRID, maximise IS Sharpe ratio."""
        best_sharpe = -999.0
        best_params: dict = {
            "min_confidence": _PARAM_GRID["min_confidence"][0],
            "risk_per_trade": _PARAM_GRID["risk_per_trade"][0],
        }
        best_metrics: dict = {}

        for conf in _PARAM_GRID["min_confidence"]:
            for risk in _PARAM_GRID["risk_per_trade"]:
                params = {"min_confidence": conf, "risk_per_trade": risk}
                metrics = self._backtest_simple(events, candles, params)
                sharpe = metrics.get("sharpe_ratio", -999.0)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_metrics = metrics

        return best_params, best_metrics

    def _backtest_simple(
        self,
        events: list[dict],
        candles: pd.DataFrame,
        params: dict,
    ) -> dict:
        """
        Simplified event-driven backtest.
        For each event above confidence threshold, simulate a trade entry.
        """
        if len(candles) == 0 or len(events) == 0:
            empty = PortfolioMetrics.compute([], [self._initial_capital], self._initial_capital)
            return empty.to_dict()

        min_conf = params.get("min_confidence", 0.45)
        risk_frac = params.get("risk_per_trade", 0.01)

        equity = self._initial_capital
        equity_curve = [equity]
        pnls: list[float] = []
        conf_model = ConfidenceModel(memory_window_minutes=120)

        candle_closes = candles["close"]

        for ev in events:
            # Compute confidence
            from ..feeds.base import EventDomain, NewsEvent
            try:
                domain = EventDomain(ev.get("domain", "UNKNOWN"))
            except ValueError:
                domain = EventDomain.UNKNOWN

            ts_str = ev.get("published_at", "")
            try:
                ts = pd.Timestamp(ts_str)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
            except (ValueError, TypeError):
                continue

            news_ev = NewsEvent(
                event_id=ev.get("event_id", ""),
                domain=domain,
                headline=ev.get("headline", ""),
                summary=ev.get("summary", ""),
                source=ev.get("source", ""),
                url="",
                published_at=ts.to_pydatetime(),
                credibility_weight=ev.get("credibility_weight", 1.0),
                keywords_matched=ev.get("keywords_matched", []),
                sentiment_score=ev.get("sentiment_score", 0.0),
                importance_score=ev.get("importance_score", 0.5),
            )
            confidence = conf_model.score(news_ev)
            if confidence < min_conf:
                continue

            # Find entry candle
            idx = candle_closes.index.searchsorted(ts)
            if idx >= len(candle_closes) - _EXIT_CANDLES:
                continue

            entry_price = float(candle_closes.iloc[idx])
            if entry_price <= 0:
                continue

            # Determine direction from sentiment
            sentiment = ev.get("sentiment_score", 0.0)
            direction = "LONG" if sentiment >= 0 else "SHORT"

            # Simple ATR-based stop using candle range
            window_start = max(0, idx - _ATR_LOOKBACK)
            window_candles = candles.iloc[window_start:idx]
            if len(window_candles) >= _MIN_ATR_CANDLES and "high" in candles.columns:
                atr = float(
                    (window_candles["high"] - window_candles["low"]).mean()
                )
            else:
                atr = entry_price * _FALLBACK_STOP_FRACTION

            stop_dist = _ATR_STOP_MULTIPLIER * atr
            risk_amount = equity * risk_frac
            size = risk_amount / max(stop_dist, 1e-8)
            size = min(size, equity / max(entry_price, 1.0))

            # Exit after _EXIT_CANDLES candles (1h at 5m)
            exit_idx = min(idx + _EXIT_CANDLES, len(candle_closes) - 1)
            exit_price = float(candle_closes.iloc[exit_idx])

            if direction == "LONG":
                gross_pnl = (exit_price - entry_price) * size
            else:
                gross_pnl = (entry_price - exit_price) * size

            commission = (entry_price * size * self._commission
                          + exit_price * size * self._commission)
            net_pnl = gross_pnl - commission

            equity += net_pnl
            equity_curve.append(equity)
            pnls.append(net_pnl)

        return PortfolioMetrics.compute(
            closed_pnls=pnls,
            equity_curve=equity_curve,
            initial_capital=self._initial_capital,
        ).to_dict()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filter_events(self, start: datetime, end: datetime) -> list[dict]:
        """Return events with published_at in [start, end)."""
        filtered = []
        for ev in self._events:
            ts_str = ev.get("published_at", "")
            try:
                ts = pd.Timestamp(ts_str)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                ts_dt = ts.to_pydatetime()
                if start <= ts_dt < end:
                    filtered.append(ev)
            except (ValueError, TypeError):
                pass  # Skip events with unparsable timestamps
        return filtered

    def _filter_candles(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Return candles with index in [start, end)."""
        mask = (self._candles.index >= start) & (self._candles.index < end)
        return self._candles[mask]

    def _aggregate_windows(self, window_results: list[dict]) -> dict:
        """Compute aggregate statistics across all OOS windows."""
        oos_list = [w["oos"] for w in window_results if w.get("oos")]
        if not oos_list:
            return {}
        sharpes = [r.get("sharpe_ratio", 0.0) for r in oos_list]
        returns = [r.get("total_return_pct", 0.0) for r in oos_list]
        dds = [r.get("max_drawdown_pct", 0.0) for r in oos_list]
        pfs = [r.get("profit_factor", 0.0) for r in oos_list]
        win_rates = [r.get("win_rate_pct", 0.0) for r in oos_list]
        return {
            "mean_oos_sharpe": round(float(np.mean(sharpes)), 4),
            "std_oos_sharpe": round(float(np.std(sharpes)), 4),
            "mean_oos_return_pct": round(float(np.mean(returns)), 4),
            "mean_oos_max_dd": round(float(np.mean(dds)), 4),
            "mean_profit_factor": round(float(np.mean(pfs)), 4),
            "mean_win_rate_pct": round(float(np.mean(win_rates)), 4),
            "pct_profitable_windows": round(
                float(sum(1 for s in sharpes if s > 0) / len(sharpes) * 100), 2
            ),
        }

    def _plot_equity_curves(
        self, window_results: list[dict], output_path: Path, run_name: str
    ) -> None:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available — skipping walk-forward plot")
            return

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"Walk-Forward Results: {run_name}", fontsize=13, fontweight="bold")

        # Left: OOS Sharpe per window
        sharpes = [w["oos"].get("sharpe_ratio", 0.0) for w in window_results]
        labels = [f"W{w['window_idx']+1}" for w in window_results]
        colors = ["green" if s > 0 else "red" for s in sharpes]
        ax1.bar(labels, sharpes, color=colors, alpha=0.7)
        ax1.axhline(0, color="black", linewidth=0.8)
        ax1.set_title("OOS Sharpe Ratio per Window")
        ax1.set_ylabel("Sharpe Ratio")
        ax1.grid(True, alpha=0.3, axis="y")

        # Right: OOS return per window
        returns = [w["oos"].get("total_return_pct", 0.0) for w in window_results]
        r_colors = ["green" if r > 0 else "red" for r in returns]
        ax2.bar(labels, returns, color=r_colors, alpha=0.7)
        ax2.axhline(0, color="black", linewidth=0.8)
        ax2.set_title("OOS Total Return (%) per Window")
        ax2.set_ylabel("Return (%)")
        ax2.grid(True, alpha=0.3, axis="y")

        plt.tight_layout()
        plt.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info("Walk-forward plot saved: %s", output_path)
