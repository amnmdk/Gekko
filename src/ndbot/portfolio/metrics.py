"""
Portfolio performance metrics calculator.

Computes:
  - Total return %
  - Sharpe Ratio (annualised)
  - Sortino Ratio
  - Max Drawdown %
  - Profit Factor
  - Expectancy ($/trade)
  - Win Rate %
  - Average Win / Average Loss
  - Calmar Ratio
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class PerformanceReport:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_return_pct: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    annualised_return_pct: float

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "total_pnl_usd": round(self.total_pnl, 4),
            "total_return_pct": round(self.total_return_pct, 4),
            "avg_win_usd": round(self.avg_win, 4),
            "avg_loss_usd": round(self.avg_loss, 4),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy_usd": round(self.expectancy, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "annualised_return_pct": round(self.annualised_return_pct, 4),
        }


class PortfolioMetrics:
    """
    Compute performance metrics from a list of closed trade PnLs
    and an equity curve.
    """

    @staticmethod
    def compute(
        closed_pnls: list[float],
        equity_curve: list[float],
        initial_capital: float,
        holding_minutes_avg: float = 60.0,
        risk_free_rate: float = 0.0,
    ) -> PerformanceReport:
        """
        Parameters
        ----------
        closed_pnls: list[float]
            List of realised PnL per closed trade.
        equity_curve: list[float]
            Equity values over time (same frequency as trades or periodic).
        initial_capital: float
            Starting equity.
        holding_minutes_avg: float
            Average holding time in minutes (for annualisation).
        risk_free_rate: float
            Annual risk-free rate (decimal, e.g. 0.05).
        """
        if not closed_pnls:
            return PerformanceReport(
                total_trades=0, winning_trades=0, losing_trades=0,
                win_rate=0.0, total_pnl=0.0, total_return_pct=0.0,
                avg_win=0.0, avg_loss=0.0, profit_factor=0.0,
                expectancy=0.0, max_drawdown_pct=0.0,
                sharpe_ratio=0.0, sortino_ratio=0.0, calmar_ratio=0.0,
                annualised_return_pct=0.0,
            )

        wins = [p for p in closed_pnls if p > 0]
        losses = [p for p in closed_pnls if p <= 0]

        total_trades = len(closed_pnls)
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        total_pnl = sum(closed_pnls)
        total_return_pct = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0.0

        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # --- Drawdown ---
        eq = np.array(equity_curve if equity_curve else [initial_capital])
        rolling_max = np.maximum.accumulate(eq)
        drawdowns = (rolling_max - eq) / rolling_max
        max_drawdown_pct = float(np.max(drawdowns)) * 100 if len(drawdowns) > 0 else 0.0

        # --- Returns series ---
        pnl_arr = np.array(closed_pnls)
        # Normalise by approximate equity at time of each trade
        approx_equity = initial_capital + np.cumsum(np.append([0], pnl_arr[:-1]))
        returns = pnl_arr / np.maximum(approx_equity, 1.0)

        # Annualisation: trades per year based on average holding time
        minutes_per_year = 365 * 24 * 60
        trades_per_year = minutes_per_year / max(holding_minutes_avg, 1.0)

        # Sharpe
        rf_per_trade = risk_free_rate / trades_per_year
        excess_returns = returns - rf_per_trade
        if len(returns) > 1 and float(np.std(returns)) > 0:
            sharpe = float(np.mean(excess_returns) / np.std(returns)) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0

        # Sortino (downside deviation)
        downside = excess_returns[excess_returns < 0]
        if len(downside) > 1 and float(np.std(downside)) > 0:
            sortino = float(np.mean(excess_returns) / np.std(downside)) * math.sqrt(trades_per_year)
        else:
            sortino = 0.0

        # Annualised return
        final_equity = equity_curve[-1] if equity_curve else initial_capital
        ann_return_pct = (
            ((final_equity / initial_capital) ** (trades_per_year / max(total_trades, 1)) - 1) * 100
            if initial_capital > 0 else 0.0
        )

        # Calmar
        calmar = (ann_return_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

        return PerformanceReport(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_return_pct=total_return_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            annualised_return_pct=ann_return_pct,
        )
