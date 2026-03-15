"""
Monte Carlo robustness testing.

Tests whether a strategy's edge survives randomness:
  1. Trade sequence reshuffling (bootstrapped PnL paths)
  2. Random entry time perturbation
  3. Noise injection into returns

Statistical output:
  - Confidence intervals for Sharpe, return, max drawdown
  - Probability of ruin at various thresholds
  - p-value for strategy vs random baseline
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Default number of Monte Carlo simulations
DEFAULT_N_SIMULATIONS = 1000

# Ruin thresholds as fraction of initial capital
RUIN_THRESHOLDS = [0.25, 0.50, 0.75]


@dataclass
class MonteCarloResult:
    """Results from a Monte Carlo robustness test."""
    n_simulations: int
    n_trades: int
    # Sharpe ratio distribution
    sharpe_mean: float
    sharpe_median: float
    sharpe_5th: float
    sharpe_95th: float
    # Return distribution
    return_mean_pct: float
    return_median_pct: float
    return_5th_pct: float
    return_95th_pct: float
    # Max drawdown distribution
    max_dd_mean_pct: float
    max_dd_median_pct: float
    max_dd_95th_pct: float
    # Risk of ruin
    prob_ruin_25: float
    prob_ruin_50: float
    prob_ruin_75: float
    # Original strategy performance
    original_sharpe: float
    original_return_pct: float
    # p-value: fraction of random runs that beat the original
    p_value_sharpe: float
    p_value_return: float

    def to_dict(self) -> dict:
        return {
            "n_simulations": self.n_simulations,
            "n_trades": self.n_trades,
            "sharpe": {
                "mean": round(self.sharpe_mean, 4),
                "median": round(self.sharpe_median, 4),
                "ci_5": round(self.sharpe_5th, 4),
                "ci_95": round(self.sharpe_95th, 4),
            },
            "return_pct": {
                "mean": round(self.return_mean_pct, 4),
                "median": round(self.return_median_pct, 4),
                "ci_5": round(self.return_5th_pct, 4),
                "ci_95": round(self.return_95th_pct, 4),
            },
            "max_drawdown_pct": {
                "mean": round(self.max_dd_mean_pct, 4),
                "median": round(self.max_dd_median_pct, 4),
                "worst_95": round(self.max_dd_95th_pct, 4),
            },
            "risk_of_ruin": {
                "25pct_loss": round(self.prob_ruin_25, 4),
                "50pct_loss": round(self.prob_ruin_50, 4),
                "75pct_loss": round(self.prob_ruin_75, 4),
            },
            "original": {
                "sharpe": round(self.original_sharpe, 4),
                "return_pct": round(self.original_return_pct, 4),
            },
            "p_values": {
                "sharpe": round(self.p_value_sharpe, 4),
                "return": round(self.p_value_return, 4),
            },
        }


class MonteCarloEngine:
    """
    Monte Carlo robustness tester for trading strategies.

    Parameters
    ----------
    n_simulations : int
        Number of random permutation runs.
    seed : int
        Random seed for reproducibility.
    """

    def __init__(self, n_simulations: int = DEFAULT_N_SIMULATIONS, seed: int = 42):
        self._n_sims = n_simulations
        self._rng = np.random.default_rng(seed)

    def run_bootstrap(
        self,
        trade_pnls: list[float],
        initial_capital: float,
        holding_minutes_avg: float = 60.0,
    ) -> MonteCarloResult:
        """
        Run bootstrap Monte Carlo by reshuffling trade sequence.

        For each simulation:
          1. Randomly permute the order of trades
          2. Compute equity curve, Sharpe, return, max drawdown
          3. Check for ruin at each threshold
        """
        pnls = np.array(trade_pnls)
        n_trades = len(pnls)

        if n_trades < 2:
            return self._empty_result(n_trades)

        # Original strategy metrics
        orig_sharpe = self._compute_sharpe(pnls, initial_capital, holding_minutes_avg)
        orig_return = float(np.sum(pnls) / initial_capital * 100)

        # Run simulations
        sharpes = np.zeros(self._n_sims)
        returns = np.zeros(self._n_sims)
        max_dds = np.zeros(self._n_sims)
        ruin_counts = {t: 0 for t in RUIN_THRESHOLDS}

        for i in range(self._n_sims):
            shuffled = self._rng.permutation(pnls)
            eq_curve = initial_capital + np.cumsum(shuffled)
            eq_curve = np.insert(eq_curve, 0, initial_capital)

            sharpes[i] = self._compute_sharpe(shuffled, initial_capital, holding_minutes_avg)
            returns[i] = float((eq_curve[-1] / initial_capital - 1) * 100)
            max_dds[i] = self._max_drawdown(eq_curve)

            # Check ruin
            min_equity = float(np.min(eq_curve))
            for threshold in RUIN_THRESHOLDS:
                if min_equity <= initial_capital * (1 - threshold):
                    ruin_counts[threshold] += 1

        # Compute p-values (fraction of random runs that beat original)
        p_sharpe = float(np.mean(sharpes >= orig_sharpe))
        p_return = float(np.mean(returns >= orig_return))

        return MonteCarloResult(
            n_simulations=self._n_sims,
            n_trades=n_trades,
            sharpe_mean=float(np.mean(sharpes)),
            sharpe_median=float(np.median(sharpes)),
            sharpe_5th=float(np.percentile(sharpes, 5)),
            sharpe_95th=float(np.percentile(sharpes, 95)),
            return_mean_pct=float(np.mean(returns)),
            return_median_pct=float(np.median(returns)),
            return_5th_pct=float(np.percentile(returns, 5)),
            return_95th_pct=float(np.percentile(returns, 95)),
            max_dd_mean_pct=float(np.mean(max_dds)),
            max_dd_median_pct=float(np.median(max_dds)),
            max_dd_95th_pct=float(np.percentile(max_dds, 95)),
            prob_ruin_25=ruin_counts[0.25] / self._n_sims,
            prob_ruin_50=ruin_counts[0.50] / self._n_sims,
            prob_ruin_75=ruin_counts[0.75] / self._n_sims,
            original_sharpe=orig_sharpe,
            original_return_pct=orig_return,
            p_value_sharpe=p_sharpe,
            p_value_return=p_return,
        )

    def run_noise_injection(
        self,
        trade_pnls: list[float],
        initial_capital: float,
        noise_std_pct: float = 5.0,
        holding_minutes_avg: float = 60.0,
    ) -> MonteCarloResult:
        """
        Test robustness by injecting random noise into trade PnLs.

        Adds Gaussian noise with std = noise_std_pct% of each trade's PnL.
        """
        pnls = np.array(trade_pnls)
        n_trades = len(pnls)

        if n_trades < 2:
            return self._empty_result(n_trades)

        orig_sharpe = self._compute_sharpe(pnls, initial_capital, holding_minutes_avg)
        orig_return = float(np.sum(pnls) / initial_capital * 100)
        noise_scale = noise_std_pct / 100.0

        sharpes = np.zeros(self._n_sims)
        returns = np.zeros(self._n_sims)
        max_dds = np.zeros(self._n_sims)
        ruin_counts = {t: 0 for t in RUIN_THRESHOLDS}

        for i in range(self._n_sims):
            noise = self._rng.normal(0, np.abs(pnls) * noise_scale + 1e-10)
            noisy_pnls = pnls + noise
            eq_curve = initial_capital + np.cumsum(noisy_pnls)
            eq_curve = np.insert(eq_curve, 0, initial_capital)

            sharpes[i] = self._compute_sharpe(noisy_pnls, initial_capital, holding_minutes_avg)
            returns[i] = float((eq_curve[-1] / initial_capital - 1) * 100)
            max_dds[i] = self._max_drawdown(eq_curve)

            min_equity = float(np.min(eq_curve))
            for threshold in RUIN_THRESHOLDS:
                if min_equity <= initial_capital * (1 - threshold):
                    ruin_counts[threshold] += 1

        p_sharpe = float(np.mean(sharpes >= orig_sharpe))
        p_return = float(np.mean(returns >= orig_return))

        return MonteCarloResult(
            n_simulations=self._n_sims,
            n_trades=n_trades,
            sharpe_mean=float(np.mean(sharpes)),
            sharpe_median=float(np.median(sharpes)),
            sharpe_5th=float(np.percentile(sharpes, 5)),
            sharpe_95th=float(np.percentile(sharpes, 95)),
            return_mean_pct=float(np.mean(returns)),
            return_median_pct=float(np.median(returns)),
            return_5th_pct=float(np.percentile(returns, 5)),
            return_95th_pct=float(np.percentile(returns, 95)),
            max_dd_mean_pct=float(np.mean(max_dds)),
            max_dd_median_pct=float(np.median(max_dds)),
            max_dd_95th_pct=float(np.percentile(max_dds, 95)),
            prob_ruin_25=ruin_counts[0.25] / self._n_sims,
            prob_ruin_50=ruin_counts[0.50] / self._n_sims,
            prob_ruin_75=ruin_counts[0.75] / self._n_sims,
            original_sharpe=orig_sharpe,
            original_return_pct=orig_return,
            p_value_sharpe=p_sharpe,
            p_value_return=p_return,
        )

    def save_report(
        self,
        result: MonteCarloResult,
        output_dir: str = "results",
        run_name: str = "mc",
    ) -> str:
        """Save Monte Carlo results to JSON."""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"monte_carlo_{run_name}_{timestamp}.json"
        with open(path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        logger.info("Monte Carlo report saved: %s", path)
        return str(path)

    @staticmethod
    def _compute_sharpe(
        pnls: np.ndarray,
        initial_capital: float,
        holding_minutes_avg: float,
    ) -> float:
        """Compute annualised Sharpe ratio from PnL array."""
        if len(pnls) < 2:
            return 0.0
        approx_equity = initial_capital + np.cumsum(np.append([0], pnls[:-1]))
        returns = pnls / np.maximum(approx_equity, 1.0)
        std = float(np.std(returns))
        if std < 1e-10:
            return 0.0
        minutes_per_year = 365 * 24 * 60
        trades_per_year = minutes_per_year / max(holding_minutes_avg, 1.0)
        return float(np.mean(returns) / std) * np.sqrt(trades_per_year)

    @staticmethod
    def _max_drawdown(equity_curve: np.ndarray) -> float:
        """Compute max drawdown as percentage."""
        peak = np.maximum.accumulate(equity_curve)
        dd = (peak - equity_curve) / np.maximum(peak, 1e-10)
        return float(np.max(dd) * 100)

    def _empty_result(self, n_trades: int) -> MonteCarloResult:
        return MonteCarloResult(
            n_simulations=self._n_sims, n_trades=n_trades,
            sharpe_mean=0, sharpe_median=0, sharpe_5th=0, sharpe_95th=0,
            return_mean_pct=0, return_median_pct=0, return_5th_pct=0, return_95th_pct=0,
            max_dd_mean_pct=0, max_dd_median_pct=0, max_dd_95th_pct=0,
            prob_ruin_25=0, prob_ruin_50=0, prob_ruin_75=0,
            original_sharpe=0, original_return_pct=0,
            p_value_sharpe=1, p_value_return=1,
        )
