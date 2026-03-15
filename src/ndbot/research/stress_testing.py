"""
Strategy Stress Testing (Step 7).

Simulates extreme market scenarios to measure strategy resilience:

  1. Flash crash       — sudden 10-30% price drop in minutes
  2. News burst        — 10× normal event frequency
  3. Extreme volatility — vol spike to 3× baseline
  4. Exchange downtime  — simulated 30-min data gap
  5. Liquidity crisis   — spread widening to 10× normal

For each scenario, measures:
  - Max drawdown during stress
  - Recovery time (bars to recover to pre-stress equity)
  - Risk of ruin probability
  - P&L during stress period
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StressScenario:
    """Definition of a single stress scenario."""
    name: str
    description: str
    price_shock_pct: float = 0.0       # Immediate price change %
    volatility_multiplier: float = 1.0  # Vol scaling factor
    spread_multiplier: float = 1.0      # Spread widening factor
    data_gap_bars: int = 0              # Simulated data outage
    event_burst_multiplier: float = 1.0  # Event frequency multiplier
    duration_bars: int = 50             # How long the scenario lasts


@dataclass
class StressResult:
    """Result of a single stress test."""
    scenario_name: str
    max_drawdown_pct: float
    recovery_bars: int         # Bars to recover (-1 if not recovered)
    stress_pnl_pct: float      # PnL during stress period
    risk_of_ruin: float        # Estimated RoR under stress
    survived: bool             # Did strategy survive?
    peak_to_trough: float      # Worst peak-to-trough in stress period
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scenario_name": self.scenario_name,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "recovery_bars": self.recovery_bars,
            "stress_pnl_pct": round(self.stress_pnl_pct, 4),
            "risk_of_ruin": round(self.risk_of_ruin, 6),
            "survived": self.survived,
            "peak_to_trough": round(self.peak_to_trough, 4),
            "details": self.details,
        }


# Pre-defined institutional stress scenarios
SCENARIOS = [
    StressScenario(
        name="flash_crash",
        description="Sudden 20% price crash in 5 bars",
        price_shock_pct=-20.0,
        volatility_multiplier=5.0,
        spread_multiplier=10.0,
        duration_bars=5,
    ),
    StressScenario(
        name="gradual_crash",
        description="Slow 30% decline over 100 bars",
        price_shock_pct=-30.0,
        volatility_multiplier=2.0,
        spread_multiplier=3.0,
        duration_bars=100,
    ),
    StressScenario(
        name="volatility_spike",
        description="Volatility triples for 50 bars",
        price_shock_pct=0.0,
        volatility_multiplier=3.0,
        spread_multiplier=2.0,
        duration_bars=50,
    ),
    StressScenario(
        name="news_burst",
        description="10x event frequency for 20 bars",
        event_burst_multiplier=10.0,
        volatility_multiplier=2.0,
        duration_bars=20,
    ),
    StressScenario(
        name="exchange_downtime",
        description="30-bar data gap simulating exchange outage",
        data_gap_bars=30,
        duration_bars=30,
    ),
    StressScenario(
        name="liquidity_crisis",
        description="Spreads widen 10x, partial fills only",
        spread_multiplier=10.0,
        volatility_multiplier=1.5,
        duration_bars=50,
    ),
    StressScenario(
        name="v_shaped_recovery",
        description="15% crash followed by rapid recovery",
        price_shock_pct=-15.0,
        volatility_multiplier=4.0,
        spread_multiplier=5.0,
        duration_bars=20,
    ),
]


class StrategyStressTester:
    """
    Runs stress tests on strategy return series.

    Injects synthetic stress scenarios into historical returns
    and measures strategy behaviour under extreme conditions.
    """

    def __init__(
        self,
        ruin_threshold: float = 0.50,  # 50% drawdown = ruin
        seed: int = 42,
    ) -> None:
        self._ruin_threshold = ruin_threshold
        self._rng = np.random.RandomState(seed)

    def run_all(
        self,
        returns: np.ndarray,
        initial_equity: float = 10000.0,
        scenarios: list[StressScenario] | None = None,
    ) -> list[StressResult]:
        """
        Run all stress scenarios on a return series.

        Parameters
        ----------
        returns : np.ndarray
            Historical strategy returns (daily or per-bar).
        initial_equity : float
            Starting capital.
        scenarios : list, optional
            Custom scenarios (defaults to SCENARIOS).

        Returns
        -------
        list[StressResult]
        """
        test_scenarios = scenarios or SCENARIOS
        results = []

        for scenario in test_scenarios:
            result = self._run_scenario(
                returns, initial_equity, scenario,
            )
            results.append(result)
            logger.info(
                "Stress test [%s]: DD=%.2f%% recovery=%d survived=%s",
                scenario.name, result.max_drawdown_pct * 100,
                result.recovery_bars, result.survived,
            )

        return results

    def _run_scenario(
        self,
        returns: np.ndarray,
        initial_equity: float,
        scenario: StressScenario,
    ) -> StressResult:
        """Simulate a single stress scenario."""
        # Create stressed return series
        stressed = self._inject_stress(returns, scenario)

        # Compute equity curve under stress
        equity = [initial_equity]
        for r in stressed:
            eq = equity[-1] * (1 + r)
            equity.append(max(0, eq))

        equity_arr = np.array(equity)

        # Compute metrics
        peak = np.maximum.accumulate(equity_arr)
        drawdown = (peak - equity_arr) / np.maximum(peak, 1e-10)
        max_dd = float(np.max(drawdown))

        # Stress period PnL
        stress_start = len(returns)
        stress_end = stress_start + scenario.duration_bars
        stress_end = min(stress_end, len(equity_arr) - 1)
        stress_pnl = (
            (equity_arr[stress_end] - equity_arr[stress_start])
            / max(equity_arr[stress_start], 1e-10)
        )

        # Recovery time
        recovery_bars = self._compute_recovery(
            equity_arr, stress_start,
        )

        # Risk of ruin
        ror = self._estimate_risk_of_ruin(stressed)

        # Survived?
        survived = max_dd < self._ruin_threshold

        # Peak to trough in stress window
        stress_equity = equity_arr[stress_start:stress_end + 1]
        if len(stress_equity) > 1:
            stress_peak = float(np.max(stress_equity))
            stress_trough = float(np.min(stress_equity))
            peak_to_trough = (
                (stress_peak - stress_trough)
                / max(stress_peak, 1e-10)
            )
        else:
            peak_to_trough = 0.0

        return StressResult(
            scenario_name=scenario.name,
            max_drawdown_pct=max_dd,
            recovery_bars=recovery_bars,
            stress_pnl_pct=float(stress_pnl),
            risk_of_ruin=ror,
            survived=survived,
            peak_to_trough=peak_to_trough,
            details={
                "scenario_description": scenario.description,
                "price_shock_pct": scenario.price_shock_pct,
                "vol_multiplier": scenario.volatility_multiplier,
                "duration_bars": scenario.duration_bars,
                "final_equity": round(float(equity_arr[-1]), 2),
            },
        )

    def _inject_stress(
        self,
        returns: np.ndarray,
        scenario: StressScenario,
    ) -> np.ndarray:
        """
        Create a stressed return series by appending
        the scenario's stressed period after the original returns.
        """
        base_vol = float(np.std(returns)) if len(returns) > 1 else 0.01

        stressed_returns = []

        # Apply price shock distributed across duration
        shock_per_bar = scenario.price_shock_pct / 100.0 / max(
            scenario.duration_bars, 1,
        )

        for i in range(scenario.duration_bars):
            # Data gap: zero return during outage
            if i < scenario.data_gap_bars:
                stressed_returns.append(0.0)
                continue

            # Base noise with stressed volatility
            noise = self._rng.normal(
                0, base_vol * scenario.volatility_multiplier,
            )
            # Add distributed shock
            bar_return = shock_per_bar + noise
            stressed_returns.append(bar_return)

        # Recovery period (additional bars at normal vol)
        for _ in range(50):
            recovery_ret = self._rng.normal(0, base_vol)
            stressed_returns.append(recovery_ret)

        return np.concatenate([
            returns, np.array(stressed_returns),
        ])

    def _compute_recovery(
        self,
        equity: np.ndarray,
        stress_start: int,
    ) -> int:
        """
        Compute bars to recover to pre-stress equity level.
        Returns -1 if no recovery.
        """
        if stress_start >= len(equity):
            return -1

        pre_stress_equity = equity[stress_start]
        for i in range(stress_start + 1, len(equity)):
            if equity[i] >= pre_stress_equity:
                return i - stress_start
        return -1

    def _estimate_risk_of_ruin(
        self, returns: np.ndarray,
    ) -> float:
        """Estimate risk of ruin under stressed conditions."""
        if len(returns) < 5:
            return 0.5
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))
        if std_r == 0:
            return 0.0 if mean_r > 0 else 1.0

        edge = mean_r / std_r
        if edge >= 1.0:
            return 0.0
        if edge <= -1.0:
            return 1.0

        # Analytical approximation: RoR = ((1-edge)/(1+edge))^N
        capital_units = 20  # Assume 20 risk units
        try:
            ror = ((1 - edge) / (1 + edge)) ** capital_units
            return max(0.0, min(1.0, ror))
        except (OverflowError, ZeroDivisionError):
            return 0.5

    def summary(self, results: list[StressResult]) -> dict:
        """Generate stress test summary."""
        return {
            "total_scenarios": len(results),
            "scenarios_survived": sum(
                1 for r in results if r.survived
            ),
            "worst_drawdown": max(
                (r.max_drawdown_pct for r in results), default=0,
            ),
            "avg_recovery_bars": (
                np.mean([
                    r.recovery_bars for r in results
                    if r.recovery_bars > 0
                ]) if any(r.recovery_bars > 0 for r in results) else -1
            ),
            "max_risk_of_ruin": max(
                (r.risk_of_ruin for r in results), default=0,
            ),
            "results": [r.to_dict() for r in results],
        }
