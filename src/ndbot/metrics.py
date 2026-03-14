"""
Top-level metrics utilities and reporting helpers.
Used by CLI for displaying formatted output.
"""
from __future__ import annotations

from rich import box
from rich.console import Console
from rich.table import Table

console = Console()


def print_performance_table(summary: dict, title: str = "Performance Summary") -> None:
    """Print a rich-formatted performance table."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        highlight=True,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Metric", style="dim", width=28)
    table.add_column("Value", justify="right", width=18)

    rows = [
        ("Initial Capital", f"${summary.get('initial_capital', 0):.2f}"),
        ("Final Equity", f"${summary.get('equity', 0):.4f}"),
        ("Total Return", f"{summary.get('return_pct', 0):.4f}%"),
        ("Total PnL", f"${summary.get('total_pnl_usd', 0):.4f}"),
        ("Total Trades", str(summary.get("total_trades", 0))),
        ("Winning Trades", str(summary.get("winning_trades", 0))),
        ("Losing Trades", str(summary.get("losing_trades", 0))),
        ("Win Rate", f"{summary.get('win_rate_pct', 0):.2f}%"),
        ("Avg Win", f"${summary.get('avg_win_usd', 0):.4f}"),
        ("Avg Loss", f"${summary.get('avg_loss_usd', 0):.4f}"),
        ("Profit Factor", f"{summary.get('profit_factor', 0):.4f}"),
        ("Expectancy", f"${summary.get('expectancy_usd', 0):.4f}"),
        ("Max Drawdown", f"{summary.get('max_drawdown_pct', 0):.4f}%"),
        ("Sharpe Ratio", f"{summary.get('sharpe_ratio', 0):.4f}"),
        ("Sortino Ratio", f"{summary.get('sortino_ratio', 0):.4f}"),
        ("Calmar Ratio", f"{summary.get('calmar_ratio', 0):.4f}"),
        ("Ann. Return", f"{summary.get('annualised_return_pct', 0):.4f}%"),
    ]

    for metric, val in rows:
        # Colour code PnL and return
        style = ""
        if "Return" in metric or "PnL" in metric or "Win" in metric:
            try:
                num = float(val.replace("%", "").replace("$", ""))
                style = "green" if num >= 0 else "red"
            except ValueError:
                pass
        table.add_row(metric, val, style=style)

    console.print(table)


def print_event_table(events: list[dict], limit: int = 20, title: str = "Recent Events") -> None:
    table = Table(title=title, box=box.SIMPLE, show_header=True, header_style="bold yellow")
    table.add_column("Domain", width=14)
    table.add_column("Headline", width=60, no_wrap=True)
    table.add_column("Source", width=18)
    table.add_column("Published", width=20)
    table.add_column("Sentiment", width=10, justify="right")

    for ev in events[:limit]:
        sent = ev.get("sentiment_score", 0.0)
        sent_str = f"{sent:.2f}"
        sent_style = "green" if sent > 0.1 else "red" if sent < -0.1 else "dim"
        table.add_row(
            ev.get("domain", ""),
            ev.get("headline", "")[:60],
            ev.get("source", "")[:18],
            str(ev.get("published_at", ""))[:19],
            f"[{sent_style}]{sent_str}[/{sent_style}]",
        )
    console.print(table)


def print_trade_table(trades: list[dict], limit: int = 20, title: str = "Recent Trades") -> None:
    table = Table(title=title, box=box.SIMPLE, show_header=True, header_style="bold magenta")
    table.add_column("ID", width=14)
    table.add_column("Dir", width=6)
    table.add_column("Symbol", width=12)
    table.add_column("Entry", width=12, justify="right")
    table.add_column("Exit", width=12, justify="right")
    table.add_column("PnL", width=10, justify="right")
    table.add_column("Reason", width=16)

    for t in trades[:limit]:
        pnl = t.get("realised_pnl", 0.0) or 0.0
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            str(t.get("position_id", ""))[:12],
            t.get("direction", ""),
            t.get("symbol", ""),
            f"{t.get('entry_price', 0):.2f}",
            f"{t.get('exit_price', 0) or 0:.2f}",
            f"[{pnl_style}]{pnl:.4f}[/{pnl_style}]",
            t.get("close_reason", "-") or "-",
        )
    console.print(table)


def print_walkforward_table(windows: list[dict], title: str = "Walk-Forward Results") -> None:
    table = Table(title=title, box=box.SIMPLE, show_header=True, header_style="bold blue")
    table.add_column("Win", width=4)
    table.add_column("Test Start", width=12)
    table.add_column("Test End", width=12)
    table.add_column("OOS Sharpe", width=12, justify="right")
    table.add_column("OOS Return%", width=12, justify="right")
    table.add_column("OOS MaxDD%", width=12, justify="right")
    table.add_column("OOS Trades", width=10, justify="right")

    for w in windows:
        oos = w.get("oos", {})
        sharpe = oos.get("sharpe_ratio", 0.0)
        ret = oos.get("total_return_pct", 0.0)
        dd = oos.get("max_drawdown_pct", 0.0)
        n = oos.get("total_trades", 0)
        sharpe_style = "green" if sharpe > 0 else "red"
        ret_style = "green" if ret > 0 else "red"
        table.add_row(
            str(w.get("window_idx", 0) + 1),
            w.get("test_start", ""),
            w.get("test_end", ""),
            f"[{sharpe_style}]{sharpe:.4f}[/{sharpe_style}]",
            f"[{ret_style}]{ret:.4f}[/{ret_style}]",
            f"{dd:.4f}",
            str(n),
        )
    console.print(table)
