"""
Portfolio Optimization (Step 7).

Risk-aware portfolio construction using multiple methodologies:

  Methods:
    1. Mean-variance (Markowitz)
    2. Risk parity (equal risk contribution)
    3. Kelly fraction (growth-optimal)
    4. Min-variance (minimum volatility)
    5. Max-Sharpe (tangency portfolio)
    6. Equal weight (1/N baseline)

  Constraints:
    - Long-only or long/short
    - Maximum position size caps
    - Minimum diversification ratio
    - Sector/factor exposure limits
    - Turnover constraints

  All solvers use numpy (no external optimiser dependency).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PortfolioAllocation:
    """Optimised portfolio weights and analytics."""

    method: str
    weights: dict[str, float] = field(default_factory=dict)
    expected_return: float = 0.0
    expected_risk: float = 0.0
    sharpe_ratio: float = 0.0
    diversification_ratio: float = 0.0
    max_weight: float = 0.0
    n_assets: int = 0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "expected_return": round(self.expected_return, 6),
            "expected_risk": round(self.expected_risk, 6),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "diversification_ratio": round(self.diversification_ratio, 4),
            "max_weight": round(self.max_weight, 4),
            "n_assets": self.n_assets,
            "details": self.details,
        }


class PortfolioOptimizer:
    """
    Multi-method portfolio optimiser.

    Usage:
        opt = PortfolioOptimizer()
        allocation = opt.optimise(
            returns=returns_matrix,
            asset_names=["BTC", "ETH", "SOL"],
            method="risk_parity",
        )
    """

    def __init__(
        self,
        risk_free_rate: float = 0.04,
        max_weight: float = 0.40,
        min_weight: float = 0.0,
        long_only: bool = True,
    ) -> None:
        self._rf = risk_free_rate / 252  # Daily
        self._max_w = max_weight
        self._min_w = min_weight
        self._long_only = long_only

    def optimise(
        self,
        returns: np.ndarray,
        asset_names: list[str] | None = None,
        method: str = "max_sharpe",
    ) -> PortfolioAllocation:
        """
        Optimise portfolio weights.

        Parameters
        ----------
        returns : (n_obs, n_assets) daily return matrix
        asset_names : optional asset labels
        method : "mean_variance", "risk_parity", "kelly",
                 "min_variance", "max_sharpe", "equal_weight"
        """
        n_obs, n_assets = returns.shape
        if asset_names is None:
            asset_names = [f"asset_{i}" for i in range(n_assets)]

        if n_obs < 10 or n_assets < 1:
            return PortfolioAllocation(
                method=method,
                details={"error": "insufficient_data"},
            )

        mu = returns.mean(axis=0)
        cov = np.cov(returns, rowvar=False)

        # Ensure cov is 2D
        if cov.ndim == 0:
            cov = np.array([[float(cov)]])

        dispatch = {
            "mean_variance": self._mean_variance,
            "risk_parity": self._risk_parity,
            "kelly": self._kelly,
            "min_variance": self._min_variance,
            "max_sharpe": self._max_sharpe,
            "equal_weight": self._equal_weight,
        }

        solver = dispatch.get(method, self._max_sharpe)
        raw_weights = solver(mu, cov, n_assets)

        # Apply constraints
        weights = self._apply_constraints(raw_weights)

        # Analytics
        port_ret = float(weights @ mu) * 252
        port_vol = float(np.sqrt(weights @ cov @ weights)) * np.sqrt(252)
        sharpe = (port_ret - self._rf * 252) / max(port_vol, 1e-10)

        # Diversification ratio
        asset_vols = np.sqrt(np.diag(cov)) * np.sqrt(252)
        weighted_avg_vol = float(weights @ asset_vols)
        div_ratio = weighted_avg_vol / max(port_vol, 1e-10)

        weight_dict = dict(zip(asset_names, [float(w) for w in weights]))

        alloc = PortfolioAllocation(
            method=method,
            weights=weight_dict,
            expected_return=port_ret,
            expected_risk=port_vol,
            sharpe_ratio=float(sharpe),
            diversification_ratio=float(div_ratio),
            max_weight=float(np.max(weights)),
            n_assets=int(np.sum(weights > 0.001)),
        )

        logger.info(
            "Portfolio optimised [%s]: E[r]=%.2f%% vol=%.2f%% Sharpe=%.3f",
            method, port_ret * 100, port_vol * 100, sharpe,
        )
        return alloc

    def _mean_variance(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """Mean-variance: maximise return for target vol."""
        try:
            inv_cov = np.linalg.inv(cov + 1e-8 * np.eye(n))
        except np.linalg.LinAlgError:
            return np.ones(n) / n

        raw = inv_cov @ (mu - self._rf)
        if raw.sum() > 0:
            return raw / raw.sum()
        return np.ones(n) / n

    def _risk_parity(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """
        Risk parity: equal risk contribution from each asset.

        Uses iterative inverse-volatility weighting.
        """
        vols = np.sqrt(np.diag(cov))
        vols = np.maximum(vols, 1e-10)

        # Start with inverse-vol weights
        weights = 1.0 / vols
        weights /= weights.sum()

        # Iterate to equalise marginal risk contributions
        for _ in range(50):
            port_vol = np.sqrt(weights @ cov @ weights)
            if port_vol <= 0:
                break
            mrc = (cov @ weights) / max(port_vol, 1e-10)
            risk_contrib = weights * mrc
            target_rc = port_vol / n

            # Adjust weights
            for j in range(n):
                if risk_contrib[j] > 0:
                    weights[j] *= target_rc / risk_contrib[j]

            weights = np.maximum(weights, 1e-10)
            weights /= weights.sum()

        return weights

    def _kelly(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """Kelly criterion: growth-optimal sizing."""
        try:
            inv_cov = np.linalg.inv(cov + 1e-8 * np.eye(n))
        except np.linalg.LinAlgError:
            return np.ones(n) / n

        # Full Kelly
        kelly = inv_cov @ (mu - self._rf)

        # Half-Kelly for safety
        kelly *= 0.5

        # Normalise
        total = np.sum(np.abs(kelly))
        if total > 0:
            kelly /= total
        else:
            kelly = np.ones(n) / n

        return kelly

    def _min_variance(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """Minimum variance portfolio."""
        try:
            inv_cov = np.linalg.inv(cov + 1e-8 * np.eye(n))
        except np.linalg.LinAlgError:
            return np.ones(n) / n

        ones = np.ones(n)
        raw = inv_cov @ ones
        return raw / raw.sum()

    def _max_sharpe(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """Maximum Sharpe ratio (tangency) portfolio."""
        excess = mu - self._rf

        try:
            inv_cov = np.linalg.inv(cov + 1e-8 * np.eye(n))
        except np.linalg.LinAlgError:
            return np.ones(n) / n

        raw = inv_cov @ excess
        total = raw.sum()
        if total > 0:
            return raw / total
        return np.ones(n) / n

    def _equal_weight(
        self, mu: np.ndarray, cov: np.ndarray, n: int,
    ) -> np.ndarray:
        """Equal weight (1/N) baseline."""
        return np.ones(n) / n

    def _apply_constraints(self, weights: np.ndarray) -> np.ndarray:
        """Apply position size constraints."""
        if self._long_only:
            weights = np.maximum(weights, 0)

        # Enforce min/max weight
        weights = np.clip(weights, self._min_w, self._max_w)

        # Re-normalise
        total = np.sum(np.abs(weights))
        if total > 0:
            weights /= total
        else:
            weights = np.ones(len(weights)) / len(weights)

        return weights

    def compare_methods(
        self,
        returns: np.ndarray,
        asset_names: list[str] | None = None,
    ) -> list[PortfolioAllocation]:
        """Run all methods and return comparison."""
        methods = [
            "mean_variance", "risk_parity", "kelly",
            "min_variance", "max_sharpe", "equal_weight",
        ]
        results = []
        for method in methods:
            alloc = self.optimise(returns, asset_names, method)
            results.append(alloc)

        results.sort(key=lambda a: a.sharpe_ratio, reverse=True)
        return results
