"""
ndbot CLI — entry point for all commands.

Commands
--------
  simulate        Run event-driven simulation with synthetic data
  backtest        Replay stored events + candles
  event-study     Run event study analysis
  walkforward     Run walk-forward validation
  grid            Parameter grid search
  paper           Run paper trading (sandbox/testnet only)
  status          Show recent runs and system status
  seed-demo       Generate demo data and run a quick simulation
  export          Export events/trades from a run to CSV or JSON
  validate-config Validate a config file and report health check
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import click
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .config.loader import load_config
from .config.settings import BotConfig
from .metrics import (
    print_performance_table,
    print_trade_table,
    print_walkforward_table,
)
from .storage.database import Database

console = Console()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(level: str = "INFO") -> None:
    from logging.handlers import RotatingFileHandler

    log_level = getattr(logging, level.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    # Console handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(log_level)
    root.addHandler(sh)

    # Rotating file handler — logs/ndbot.log (10 MB × 3 backups)
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        logs_dir / "ndbot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)  # Always log DEBUG to file regardless of console level
    root.addHandler(fh)

    # Silence noisy third-party loggers
    for name in ("urllib3", "ccxt", "aiohttp", "feedparser"):
        logging.getLogger(name).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="ndbot")
def main():
    """ndbot — News-Driven Intraday Trading Research Framework"""
    pass


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True),
              help="Path to YAML config file")
@click.option("--events", default=40, show_default=True,
              help="Number of synthetic events per domain")
@click.option("--candles", default=500, show_default=True,
              help="Number of synthetic candles")
@click.option("--seed", default=42, show_default=True,
              help="Random seed for reproducibility")
@click.option("--log-level", default="INFO", show_default=True)
def simulate(config: str, events: int, candles: int, seed: int, log_level: str):
    """Run a simulation with synthetic data. No external APIs required."""
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    cfg = cfg.model_copy(update={"mode": "simulate"})

    from .execution.simulate import SimulationEngine

    db = Database(cfg.storage.db_path)
    db.init()

    console.print(Panel(
        f"[bold cyan]ndbot SIMULATE[/bold cyan]\n"
        f"Config: {config}\n"
        f"Symbol: {cfg.market.symbol} | Capital: ${cfg.portfolio.initial_capital}\n"
        f"Events: {events}×2 domains | Candles: {candles} | Seed: {seed}",
        title="ndbot", border_style="cyan"
    ))

    engine = SimulationEngine(cfg, db, n_events=events, n_candles=candles, seed=seed)
    summary = engine.run()

    print_performance_table(summary, title=f"Simulation Results — {cfg.run_name}")

    trades = db.get_trades(limit=20)
    if trades:
        print_trade_table(trades, title="Last 20 Trades")

    rprint(f"\n[dim]Results saved to: {cfg.storage.db_path}[/dim]")


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------

@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--events-file", type=click.Path(exists=True), default=None,
              help="JSON file of stored events (default: load from DB)")
@click.option("--candles-file", type=click.Path(exists=True), default=None,
              help="CSV file of OHLCV candles (default: synthetic)")
@click.option("--seed", default=42, show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def backtest(
    config: str,
    events_file: Optional[str],
    candles_file: Optional[str],
    seed: int,
    log_level: str,
):
    """
    Replay stored events and candles in backtest mode.
    If no data files provided, falls back to synthetic data.
    """
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    cfg = cfg.model_copy(update={"mode": "backtest"})

    from .execution.simulate import SimulationEngine
    from .market.regime import RegimeDetector
    from .market.synthetic_candles import SyntheticCandleGenerator

    db = Database(cfg.storage.db_path)
    db.init()

    # Load candles
    if candles_file:
        import pandas as pd
        candles_df = pd.read_csv(candles_file, index_col=0, parse_dates=True)
        candles_df.index = pd.to_datetime(candles_df.index, utc=True)
        console.print(f"[green]Loaded {len(candles_df)} candles from {candles_file}[/green]")
    else:
        gen = SyntheticCandleGenerator(
            symbol=cfg.market.symbol,
            timeframe_minutes=5,
            seed=seed,
        )
        raw = gen.generate(500)
        regime = RegimeDetector()
        candles_df = regime.add_indicators(raw)
        console.print("[yellow]No candles file — using synthetic candles[/yellow]")

    # Load events
    if events_file:
        with open(events_file) as f:
            events_list = json.load(f)
        console.print(f"[green]Loaded {len(events_list)} events from {events_file}[/green]")
    else:
        # Load from DB or use synthetic
        events_list = db.get_events(limit=500)
        if not events_list:
            console.print("[yellow]No stored events — using synthetic events[/yellow]")
        else:
            console.print(f"[green]Loaded {len(events_list)} events from DB[/green]")

    console.print(Panel(
        f"[bold cyan]ndbot BACKTEST[/bold cyan]\n"
        f"Candles: {len(candles_df)} | Events: {len(events_list) if events_list else 'synthetic'}",
        title="ndbot", border_style="blue"
    ))

    engine = SimulationEngine(
        cfg, db,
        n_events=40, n_candles=500, seed=seed,
        external_candles=candles_df,
        external_events=events_list if events_list else None,
    )
    summary = engine.run()

    print_performance_table(summary, title=f"Backtest Results — {cfg.run_name}")
    trades = db.get_trades(limit=20)
    if trades:
        print_trade_table(trades, title="Last 20 Trades")


# ---------------------------------------------------------------------------
# event-study
# ---------------------------------------------------------------------------

@main.command("event-study")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default="results", show_default=True)
@click.option("--n-events", default=30, show_default=True,
              help="Synthetic events to generate if no stored events")
@click.option("--seed", default=42, show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def event_study(config: str, output_dir: str, n_events: int, seed: int, log_level: str):
    """Run an event study over stored or synthetic events."""
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)

    from .classifier.keyword_classifier import KeywordClassifier
    from .feeds.base import EventDomain
    from .feeds.synthetic import SyntheticFeed
    from .market.regime import RegimeDetector
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .research.event_study import EventStudy

    db = Database(cfg.storage.db_path)
    db.init()

    # Load or generate events
    events_list = db.get_events(limit=500)
    if not events_list:
        console.print("[yellow]No stored events — generating synthetic events[/yellow]")
        classifier = KeywordClassifier()
        all_events = []
        for domain in [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]:
            feed = SyntheticFeed(domain=domain, seed=seed)
            batch = feed.generate_batch(n_events)
            for ev in batch:
                classifier.enrich(ev)
            all_events.extend(batch)
        events_list = [ev.to_dict() for ev in all_events]

    # Generate synthetic candles
    gen = SyntheticCandleGenerator(symbol=cfg.market.symbol, seed=seed)
    raw = gen.generate(2000)
    regime = RegimeDetector()
    candles = regime.add_indicators(raw)

    tf_minutes = 5
    study = EventStudy(
        candles=candles,
        pre_candles=cfg.research.pre_event_candles,
        post_candles=cfg.research.post_event_candles,
        timeframe_minutes=tf_minutes,
    )

    console.print(Panel(
        f"[bold cyan]ndbot EVENT STUDY[/bold cyan]\n"
        f"Events: {len(events_list)} | Candles: {len(candles)}\n"
        f"Window: -{cfg.research.pre_event_candles} / +{cfg.research.post_event_candles} candles",
        title="ndbot", border_style="green"
    ))

    report = study.run(
        events=events_list,
        output_dir=output_dir,
        run_name=cfg.run_name,
    )

    # Print aggregate
    agg = report.get("aggregate", {})
    console.print(f"\n[bold]Event Study Results[/bold] — {report.get('n_events', 0)} events")
    for horizon, stats in agg.items():
        if isinstance(stats, dict) and "mean" in stats:
            console.print(
                f"  {horizon:<12} mean={stats['mean']:+.4f}%  "
                f"t={stats.get('t_stat', 0):.2f}  "
                f"pct+={stats.get('pct_positive', 0):.1f}%  "
                f"n={stats.get('n', 0)}"
            )
    console.print(f"\n[dim]Outputs saved to: {output_dir}/[/dim]")


# ---------------------------------------------------------------------------
# walkforward
# ---------------------------------------------------------------------------

@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default="results", show_default=True)
@click.option("--n-events", default=200, show_default=True)
@click.option("--seed", default=42, show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def walkforward(config: str, output_dir: str, n_events: int, seed: int, log_level: str):
    """Run walk-forward out-of-sample validation."""
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)

    from .classifier.keyword_classifier import KeywordClassifier
    from .feeds.base import EventDomain
    from .feeds.synthetic import SyntheticFeed
    from .market.regime import RegimeDetector
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .research.walkforward import WalkForwardValidator

    db = Database(cfg.storage.db_path)
    db.init()

    # Generate multi-year candle history
    console.print("[cyan]Generating multi-year synthetic candle history...[/cyan]")
    total_candles = 365 * 3 * 24 * 12  # 3 years at 5m
    total_candles = min(total_candles, 50000)  # cap for Pi performance
    gen = SyntheticCandleGenerator(symbol=cfg.market.symbol, seed=seed)
    start_time = datetime.now(timezone.utc) - timedelta(minutes=5 * total_candles)
    raw = gen.generate(total_candles, start_time=start_time)
    regime = RegimeDetector()
    candles = regime.add_indicators(raw)
    console.print(f"[green]Generated {len(candles)} candles[/green]")

    # Generate synthetic events across the full history
    classifier = KeywordClassifier()
    all_events = []
    for domain in [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]:
        feed = SyntheticFeed(
            domain=domain, seed=seed,
            start_time=start_time + timedelta(days=30),
            time_step_minutes=360,
        )
        batch = feed.generate_batch(n_events)
        for ev in batch:
            classifier.enrich(ev)
        all_events.extend(batch)

    events_list = [ev.to_dict() for ev in all_events]
    console.print(f"[green]Generated {len(events_list)} events across history[/green]")

    console.print(Panel(
        f"[bold cyan]ndbot WALK-FORWARD[/bold cyan]\n"
        f"Train: {cfg.research.train_days}d | Test: {cfg.research.test_days}d"
        f" | Step: {cfg.research.step_days}d\n"
        f"Events: {len(events_list)} | Candles: {len(candles)}",
        title="ndbot", border_style="blue"
    ))

    validator = WalkForwardValidator(
        events=events_list,
        candles=candles,
        train_days=cfg.research.train_days,
        test_days=cfg.research.test_days,
        step_days=cfg.research.step_days,
        initial_capital=cfg.portfolio.initial_capital,
        commission_rate=cfg.portfolio.commission_rate,
    )

    report = validator.run(output_dir=output_dir, run_name=cfg.run_name)

    # Save windows to DB
    for window in report.get("windows", []):
        db.save_walkforward_result(run_id="wf_" + cfg.run_name, window=window)

    windows = report.get("windows", [])
    if windows:
        print_walkforward_table(windows, title=f"Walk-Forward: {cfg.run_name}")

    agg = report.get("aggregate_oos", {})
    if agg:
        console.print("\n[bold]Aggregate OOS Metrics[/bold]")
        for k, v in agg.items():
            console.print(f"  {k:<30} {v}")

    console.print(f"\n[dim]Outputs saved to: {output_dir}/[/dim]")


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------

@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default="results", show_default=True)
@click.option("--n-events", default=100, show_default=True)
@click.option("--seed", default=42, show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def grid(config: str, output_dir: str, n_events: int, seed: int, log_level: str):
    """Parameter grid search over confidence and risk thresholds."""
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)

    from .classifier.keyword_classifier import KeywordClassifier
    from .feeds.base import EventDomain
    from .feeds.synthetic import SyntheticFeed
    from .market.regime import RegimeDetector
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .research.walkforward import _PARAM_GRID, WalkForwardValidator

    db = Database(cfg.storage.db_path)
    db.init()

    gen = SyntheticCandleGenerator(symbol=cfg.market.symbol, seed=seed)
    raw = gen.generate(1000)
    regime = RegimeDetector()
    candles = regime.add_indicators(raw)

    classifier = KeywordClassifier()
    all_events = []
    for domain in [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]:
        feed = SyntheticFeed(domain=domain, seed=seed)
        batch = feed.generate_batch(n_events)
        for ev in batch:
            classifier.enrich(ev)
        all_events.extend(batch)
    events_list = [ev.to_dict() for ev in all_events]

    run_id = f"grid_{cfg.run_name}"
    validator = WalkForwardValidator(
        events=events_list, candles=candles,
        initial_capital=cfg.portfolio.initial_capital,
        commission_rate=cfg.portfolio.commission_rate,
    )

    console.print(Panel(
        f"[bold cyan]ndbot GRID SEARCH[/bold cyan]\n"
        f"min_confidence: {_PARAM_GRID['min_confidence']}\n"
        f"risk_per_trade: {_PARAM_GRID['risk_per_trade']}",
        title="ndbot", border_style="magenta"
    ))

    from rich.table import Table
    table = Table(title="Grid Search Results", show_header=True, header_style="bold")
    table.add_column("min_conf", width=10)
    table.add_column("risk_frac", width=10)
    table.add_column("Trades", width=8)
    table.add_column("Sharpe", width=10, justify="right")
    table.add_column("Return%", width=10, justify="right")
    table.add_column("MaxDD%", width=10, justify="right")
    table.add_column("WinRate%", width=10, justify="right")

    best_sharpe = -999.0
    best_params: dict = {}

    for conf in _PARAM_GRID["min_confidence"]:
        for risk in _PARAM_GRID["risk_per_trade"]:
            params = {"min_confidence": conf, "risk_per_trade": risk}
            metrics = validator._backtest_simple(events_list, candles, params)
            db.save_grid_result(run_id=run_id, params=params, metrics=metrics)
            sharpe = metrics.get("sharpe_ratio", 0.0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params
            style = "green" if sharpe > 0 else "red"
            table.add_row(
                str(conf), str(risk),
                str(metrics.get("total_trades", 0)),
                f"[{style}]{sharpe:.4f}[/{style}]",
                f"{metrics.get('total_return_pct', 0):.4f}",
                f"{metrics.get('max_drawdown_pct', 0):.4f}",
                f"{metrics.get('win_rate_pct', 0):.2f}",
            )

    console.print(table)
    console.print(
        f"\n[bold green]Best params: {best_params} | Sharpe={best_sharpe:.4f}[/bold green]"
    )
    console.print(f"[dim]Grid results saved to DB: {cfg.storage.db_path}[/dim]")


# ---------------------------------------------------------------------------
# paper
# ---------------------------------------------------------------------------

@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--duration", default=None, type=int,
              help="Run duration in seconds (None = indefinite)")
@click.option("--log-level", default="INFO", show_default=True)
def paper(config: str, duration: Optional[int], log_level: str):
    """
    Run paper trading against exchange testnet/sandbox.

    SAFETY: DRY_RUN=True by default. Sandbox is required by default.
    Set paper.dry_run=false and paper.require_sandbox=true in config to
    enable testnet order submission.
    """
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)
    cfg = cfg.model_copy(update={"mode": "paper"})

    from .execution.paper import PaperEngine

    db = Database(cfg.storage.db_path)
    db.init()

    engine = PaperEngine(cfg, db)
    try:
        summary = asyncio.run(engine.run(duration_seconds=duration))
        print_performance_table(summary, title="Paper Trading Results")
    except RuntimeError as e:
        console.print(f"[bold red]SAFETY BLOCK:[/bold red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Paper trading stopped by user[/yellow]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
@click.option("--db", default="data/ndbot.db", show_default=True,
              help="Path to SQLite database")
@click.option("--limit", default=10, show_default=True)
def status(db: str, limit: int):
    """Show recent runs and system status."""

    if not Path(db).exists():
        console.print(f"[yellow]Database not found: {db}[/yellow]")
        console.print("[dim]Run 'ndbot simulate' first to initialise.[/dim]")
        return

    database = Database(db)
    database.init()

    runs = database.get_runs(limit=limit)
    if not runs:
        console.print("[dim]No runs found in database.[/dim]")
        return

    from rich.table import Table, box
    table = Table(
        title=f"Recent Runs — {db}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Run ID", width=18)
    table.add_column("Name", width=20)
    table.add_column("Mode", width=10)
    table.add_column("Start", width=20)
    table.add_column("Trades", width=8, justify="right")
    table.add_column("PnL", width=10, justify="right")
    table.add_column("Sharpe", width=8, justify="right")

    for r in runs:
        pnl = r.get("total_pnl") or 0.0
        sharpe = r.get("sharpe_ratio") or 0.0
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            str(r.get("run_id", ""))[:16],
            str(r.get("run_name", ""))[:20],
            r.get("mode", ""),
            str(r.get("start_time", ""))[:19],
            str(r.get("total_trades", 0)),
            f"[{pnl_style}]{pnl:.4f}[/{pnl_style}]",
            f"{sharpe:.4f}" if sharpe else "-",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# seed-demo
# ---------------------------------------------------------------------------

@main.command("seed-demo")
@click.option("--output-dir", default="results", show_default=True)
@click.option("--seed", default=1337, show_default=True)
def seed_demo(output_dir: str, seed: int):
    """
    Generate demo data and run the full pipeline end-to-end.
    No external APIs, no config file required.
    Produces performance report + event study chart in results/.
    """
    _setup_logging("INFO")
    console.print(Panel(
        "[bold cyan]ndbot SEED DEMO[/bold cyan]\n"
        "Running full pipeline with synthetic data.\n"
        "No APIs required. Results saved to results/",
        title="ndbot", border_style="bright_blue"
    ))

    import tempfile

    import yaml

    # Build minimal config in memory
    cfg_dict = {
        "run_name": "seed-demo",
        "mode": "simulate",
        "portfolio": {
            "initial_capital": 100.0,
            "max_concurrent_positions": 3,
        },
        "signals": [
            {"domain": "ENERGY_GEO", "enabled": True, "min_confidence": 0.40,
             "holding_minutes": 60, "risk_per_trade": 0.01, "rr_ratio": 2.0},
            {"domain": "AI_RELEASES", "enabled": True, "min_confidence": 0.40,
             "holding_minutes": 45, "risk_per_trade": 0.01, "rr_ratio": 2.0},
        ],
        "confirmation": {"enabled": True},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(cfg_dict, tmp)
        tmp_path = tmp.name

    try:
        cfg = load_config(tmp_path)
    finally:
        import os
        os.unlink(tmp_path)

    import hashlib
    run_id_seed = hashlib.sha256(f"seed-demo{seed}".encode()).hexdigest()[:8]
    db_path = f"data/demo_{run_id_seed}.db"
    cfg = cfg.model_copy(update={"storage": cfg.storage.model_copy(update={"db_path": db_path})})

    from .execution.simulate import SimulationEngine
    from .storage.database import Database

    db = Database(cfg.storage.db_path)
    db.init()

    engine = SimulationEngine(cfg, db, n_events=30, n_candles=600, seed=seed)
    summary = engine.run()
    print_performance_table(summary, title="Demo Simulation Results")

    # Event study
    from .classifier.keyword_classifier import KeywordClassifier
    from .feeds.base import EventDomain
    from .feeds.synthetic import SyntheticFeed
    from .market.regime import RegimeDetector
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .research.event_study import EventStudy

    classifier = KeywordClassifier()
    all_events = []
    for domain in [EventDomain.ENERGY_GEO, EventDomain.AI_RELEASES]:
        feed = SyntheticFeed(domain=domain, seed=seed)
        batch = feed.generate_batch(20)
        for ev in batch:
            classifier.enrich(ev)
        all_events.extend(batch)

    gen = SyntheticCandleGenerator(symbol="BTC/USDT", seed=seed)
    raw = gen.generate(1000)
    regime_det = RegimeDetector()
    candles = regime_det.add_indicators(raw)
    study = EventStudy(candles=candles, pre_candles=12, post_candles=48)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    study.run(
        events=[ev.to_dict() for ev in all_events],
        output_dir=output_dir,
        run_name="seed-demo",
    )

    console.print("\n[bold green]Demo complete![/bold green]")
    console.print(f"  Simulation DB:  {cfg.storage.db_path}")
    console.print(f"  Event study:    {output_dir}/event_study_seed-demo_*.png")
    console.print("\n[dim]Run 'ndbot status' to see all runs.[/dim]")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@main.command()
@click.option("--run-id", required=True, help="Run ID to export (from ndbot status)")
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv",
              show_default=True)
@click.option("--output-dir", default="results", show_default=True)
@click.option("--db", default="data/ndbot.db", show_default=True)
@click.option("--what", type=click.Choice(["trades", "events", "both"]), default="both",
              show_default=True, help="What to export")
def export(run_id: str, fmt: str, output_dir: str, db: str, what: str):
    """Export events and/or trades for a run to CSV or JSON."""
    import pandas as pd

    if not Path(db).exists():
        console.print(f"[red]Database not found: {db}[/red]")
        sys.exit(1)

    database = Database(db)
    database.init()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []

    if what in ("trades", "both"):
        trades = database.get_trades(run_id=run_id, limit=10000)
        if not trades:
            console.print(f"[yellow]No trades found for run_id={run_id}[/yellow]")
        else:
            if fmt == "csv":
                path = out_dir / f"trades_{run_id}.csv"
                pd.DataFrame(trades).to_csv(path, index=False)
            else:
                path = out_dir / f"trades_{run_id}.json"
                with open(path, "w") as f:
                    json.dump(trades, f, indent=2, default=str)
            console.print(f"[green]Exported {len(trades)} trades → {path}[/green]")
            exported.append(str(path))

    if what in ("events", "both"):
        events = database.get_events(run_id=run_id, limit=10000)
        if not events:
            console.print(f"[yellow]No events found for run_id={run_id}[/yellow]")
        else:
            if fmt == "csv":
                path = out_dir / f"events_{run_id}.csv"
                pd.DataFrame(events).to_csv(path, index=False)
            else:
                path = out_dir / f"events_{run_id}.json"
                with open(path, "w") as f:
                    json.dump(events, f, indent=2, default=str)
            console.print(f"[green]Exported {len(events)} events → {path}[/green]")
            exported.append(str(path))

    if exported:
        console.print(f"\n[dim]Files written to: {output_dir}/[/dim]")
    else:
        console.print("[yellow]Nothing exported.[/yellow]")


# ---------------------------------------------------------------------------
# validate-config
# ---------------------------------------------------------------------------

@main.command("validate-config")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--check-feeds", is_flag=True, default=False,
              help="Attempt HTTP HEAD request to each enabled feed URL")
def validate_config(config: str, check_feeds: bool):
    """Validate a config file and print a health-check report."""
    import asyncio as _asyncio

    _setup_logging("WARNING")  # Keep output clean during validation
    cfg = _load_config_or_exit(config)

    from rich.table import Table
    from rich.table import box as rbox

    table = Table(
        title=f"Config Health Check — {config}",
        box=rbox.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Section", width=22)
    table.add_column("Parameter", width=28)
    table.add_column("Value", width=28)
    table.add_column("Status", width=10)

    issues: list[str] = []

    def row(section: str, param: str, val, ok: bool, warn: str = ""):
        status = "[green]OK[/green]" if ok else "[red]WARN[/red]"
        table.add_row(section, param, str(val), status)
        if not ok and warn:
            issues.append(warn)

    # Portfolio
    row("portfolio", "initial_capital", cfg.portfolio.initial_capital,
        cfg.portfolio.initial_capital > 0, "initial_capital must be > 0")
    row("portfolio", "max_daily_loss_pct", cfg.portfolio.max_daily_loss_pct,
        0 < cfg.portfolio.max_daily_loss_pct <= 0.2,
        "max_daily_loss_pct > 20% is very aggressive")
    row("portfolio", "max_drawdown_pct", cfg.portfolio.max_drawdown_pct,
        cfg.portfolio.max_drawdown_pct <= 0.3,
        "max_drawdown_pct > 30% is extremely aggressive")
    row("portfolio", "commission_rate", cfg.portfolio.commission_rate,
        cfg.portfolio.commission_rate < 0.01,
        "commission_rate >= 1% seems very high")

    # Signals
    for sc in cfg.signals:
        row(f"signals/{sc.domain}", "min_confidence", sc.min_confidence,
            sc.min_confidence >= 0.3,
            f"Signal {sc.domain}: min_confidence < 0.3 will generate many low-quality signals")
        row(f"signals/{sc.domain}", "risk_per_trade", sc.risk_per_trade,
            sc.risk_per_trade <= 0.05,
            f"Signal {sc.domain}: risk_per_trade > 5% is aggressive")
        row(f"signals/{sc.domain}", "rr_ratio", sc.rr_ratio,
            sc.rr_ratio >= 1.0,
            f"Signal {sc.domain}: rr_ratio < 1.0 means average loss > average win")

    # Paper mode safety
    if cfg.mode == "paper":
        row("paper", "dry_run", cfg.paper.dry_run, cfg.paper.dry_run,
            "DANGER: dry_run=False in paper mode will submit real testnet orders")
        row("paper", "require_sandbox", cfg.paper.require_sandbox,
            cfg.paper.require_sandbox,
            "DANGER: require_sandbox=False may connect to live exchange")

    # Feeds
    enabled_feeds = [f for f in cfg.feeds if f.enabled]
    row("feeds", "enabled_feed_count", len(enabled_feeds),
        len(enabled_feeds) > 0 or cfg.mode == "simulate",
        "No feeds enabled. Simulate mode will use synthetic data; live modes need feeds.")

    console.print(table)

    # Optional feed URL reachability check
    if check_feeds and enabled_feeds:
        console.print("\n[cyan]Checking feed URLs...[/cyan]")
        import aiohttp

        async def _check_url(feed_cfg) -> tuple[str, bool, str]:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.head(feed_cfg.url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        return feed_cfg.name, r.status < 400, f"HTTP {r.status}"
            except Exception as exc:
                return feed_cfg.name, False, str(exc)[:50]

        results = _asyncio.run(
            _asyncio.gather(*[_check_url(f) for f in enabled_feeds])
        )
        for name, ok, detail in results:
            status = "[green]reachable[/green]" if ok else "[red]unreachable[/red]"
            console.print(f"  {name:<30} {status} ({detail})")

    # Summary
    if issues:
        console.print(f"\n[bold yellow]Warnings ({len(issues)}):[/bold yellow]")
        for i, w in enumerate(issues, 1):
            console.print(f"  {i}. {w}")
    else:
        console.print("\n[bold green]Config looks healthy.[/bold green]")

    console.print(f"\n[dim]Mode: {cfg.mode} | Symbol: {cfg.market.symbol} | "
                  f"Capital: ${cfg.portfolio.initial_capital}[/dim]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# monte-carlo
# ---------------------------------------------------------------------------

@main.command("monte-carlo")
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--n-sims", default=1000, show_default=True,
              help="Number of Monte Carlo simulations")
@click.option("--n-events", default=100, show_default=True)
@click.option("--seed", default=42, show_default=True)
@click.option("--output-dir", default="results", show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def monte_carlo(
    config: str, n_sims: int, n_events: int,
    seed: int, output_dir: str, log_level: str,
):
    """Run Monte Carlo robustness testing on strategy."""
    _setup_logging(log_level)
    cfg = _load_config_or_exit(config)

    from .execution.simulate import SimulationEngine
    from .research.monte_carlo import MonteCarloEngine

    db = Database(cfg.storage.db_path)
    db.init()

    console.print(Panel(
        f"[bold cyan]ndbot MONTE CARLO[/bold cyan]\n"
        f"Simulations: {n_sims} | Events: {n_events} | Seed: {seed}",
        title="ndbot", border_style="red"
    ))

    # Run base simulation to get trade PnLs
    console.print("[cyan]Running base simulation...[/cyan]")
    engine = SimulationEngine(cfg, db, n_events=n_events, n_candles=500, seed=seed)
    engine.run()

    # Get trade PnLs from portfolio
    trades = db.get_trades(limit=10000)
    trade_pnls = [
        t.get("realised_pnl", 0.0) or 0.0
        for t in trades if t.get("realised_pnl") is not None
    ]

    if len(trade_pnls) < 3:
        console.print("[yellow]Insufficient trades for Monte Carlo analysis[/yellow]")
        return

    mc = MonteCarloEngine(n_simulations=n_sims, seed=seed)

    # Bootstrap test
    console.print(f"[cyan]Running {n_sims} bootstrap simulations...[/cyan]")
    bootstrap = mc.run_bootstrap(
        trade_pnls, cfg.portfolio.initial_capital,
    )

    # Noise injection test
    console.print(f"[cyan]Running {n_sims} noise injection simulations...[/cyan]")
    noise = mc.run_noise_injection(
        trade_pnls, cfg.portfolio.initial_capital,
    )

    # Display results
    from rich.table import Table
    table = Table(title="Monte Carlo Robustness Results", show_header=True, header_style="bold red")
    table.add_column("Metric", width=30)
    table.add_column("Bootstrap", width=18, justify="right")
    table.add_column("Noise Injection", width=18, justify="right")

    rows = [
        ("Sharpe (mean)", f"{bootstrap.sharpe_mean:.4f}", f"{noise.sharpe_mean:.4f}"),
        ("Sharpe (5th pct)", f"{bootstrap.sharpe_5th:.4f}", f"{noise.sharpe_5th:.4f}"),
        ("Sharpe (95th pct)", f"{bootstrap.sharpe_95th:.4f}", f"{noise.sharpe_95th:.4f}"),
        ("Return % (mean)", f"{bootstrap.return_mean_pct:.4f}", f"{noise.return_mean_pct:.4f}"),
        ("Return % (5th pct)", f"{bootstrap.return_5th_pct:.4f}", f"{noise.return_5th_pct:.4f}"),
        ("Max DD % (95th)", f"{bootstrap.max_dd_95th_pct:.4f}", f"{noise.max_dd_95th_pct:.4f}"),
        ("Risk of Ruin (25%)", f"{bootstrap.prob_ruin_25:.4f}", f"{noise.prob_ruin_25:.4f}"),
        ("Risk of Ruin (50%)", f"{bootstrap.prob_ruin_50:.4f}", f"{noise.prob_ruin_50:.4f}"),
        ("p-value (Sharpe)", f"{bootstrap.p_value_sharpe:.4f}", f"{noise.p_value_sharpe:.4f}"),
        ("Original Sharpe", f"{bootstrap.original_sharpe:.4f}", f"{noise.original_sharpe:.4f}"),
    ]
    for metric, bs, ni in rows:
        table.add_row(metric, bs, ni)

    console.print(table)

    # Save reports
    mc.save_report(bootstrap, output_dir, f"{cfg.run_name}_bootstrap")
    mc.save_report(noise, output_dir, f"{cfg.run_name}_noise")
    console.print(f"\n[dim]Reports saved to: {output_dir}/[/dim]")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@main.command()
@click.option("--db", default="data/ndbot.db", show_default=True)
def health(db: str):
    """Show system health and monitoring status."""
    from .monitoring import SystemMonitor

    monitor = SystemMonitor()

    console.print(Panel(
        "[bold cyan]ndbot SYSTEM HEALTH[/bold cyan]",
        title="ndbot", border_style="green"
    ))

    health_status = monitor.get_health()
    status_style = {
        "healthy": "green",
        "degraded": "yellow",
        "critical": "red",
    }.get(health_status.overall, "dim")

    console.print(f"  Status:  [{status_style}]{health_status.overall.upper()}[/{status_style}]")
    console.print(f"  Uptime:  {health_status.uptime_seconds:.0f}s")

    if Path(db).exists():
        database = Database(db)
        database.init()
        runs = database.get_runs(limit=5)
        if runs:
            console.print(f"\n  Recent runs: {len(runs)}")
            for r in runs[:3]:
                pnl = r.get("total_pnl") or 0.0
                pnl_style = "green" if pnl >= 0 else "red"
                console.print(
                    f"    {r.get('run_name', ''):<20} "
                    f"[{pnl_style}]PnL={pnl:+.4f}[/{pnl_style}]  "
                    f"trades={r.get('total_trades', 0)}"
                )
    else:
        console.print(f"\n  [dim]No database found at {db}[/dim]")


# ---------------------------------------------------------------------------
# alpha-pipeline
# ---------------------------------------------------------------------------

@main.command("alpha-pipeline")
@click.option("--domain", default=None, help="Filter by event domain")
@click.option("--limit", default=5000, show_default=True)
@click.option("--log-level", default="INFO", show_default=True)
def alpha_pipeline(domain: str, limit: int, log_level: str):
    """Run the automated alpha discovery pipeline."""
    _setup_logging(log_level)
    from .research.pipeline import ResearchPipeline

    console.print(Panel(
        "[bold cyan]ndbot ALPHA DISCOVERY PIPELINE[/bold cyan]\n"
        f"Domain: {domain or 'ALL'} | Limit: {limit}",
        title="ndbot", border_style="magenta"
    ))

    pipeline = ResearchPipeline()
    result = pipeline.run(domain=domain, limit=limit)

    from rich.table import Table
    t = Table(
        title="Pipeline Results",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right")

    t.add_row("Events Processed", str(result.events_processed))
    t.add_row("Events Flagged", str(result.events_flagged))
    t.add_row("Categories Analysed", str(result.categories_analysed))
    t.add_row("Signals Discovered", str(result.signals_discovered))
    t.add_row(
        "Significant Signals",
        str(result.signals_significant),
    )
    t.add_row("Hypotheses Tested", str(result.hypotheses_tested))
    t.add_row("Hypotheses Rejected", str(result.hypotheses_rejected))
    t.add_row("Signals Registered", str(result.signals_registered))

    console.print(t)

    if result.errors:
        for err in result.errors:
            console.print(f"  [yellow]Warning: {err}[/yellow]")

    # Show registry summary
    summary = pipeline.registry.summary()
    console.print(f"\n[bold]Alpha Registry:[/bold] "
                  f"{summary['total_signals']} signals")
    for sig in summary.get("top_signals", [])[:3]:
        console.print(
            f"  {sig['id']:<30} "
            f"Sharpe={sig['sharpe']:.3f}  "
            f"[{sig['status']}]"
        )

    console.print(
        f"\n[dim]Results: results/pipeline_runs/{result.run_id}.json[/dim]"
    )


# ---------------------------------------------------------------------------
# validate — System Validation Report
# ---------------------------------------------------------------------------

@main.command("validate")
@click.argument("strategy_id", default="demo_strategy")
@click.option("--log-level", default="INFO", show_default=True)
def validate_cmd(strategy_id: str, log_level: str):
    """Generate a full system validation report for a strategy."""
    _setup_logging(log_level)
    import numpy as np

    from .research.validation_report import ValidationReportGenerator

    console.print(Panel(
        "[bold cyan]SYSTEM VALIDATION REPORT[/bold cyan]\n"
        f"Strategy: {strategy_id}",
        title="ndbot", border_style="magenta"
    ))

    rng = np.random.default_rng(42)
    demo_returns = rng.normal(0.0005, 0.015, 500)

    generator = ValidationReportGenerator()
    report = generator.generate(
        strategy_id=strategy_id,
        returns=demo_returns,
        bias_audit={"bias_risk_score": 0.15, "risk_level": "low", "checks_failed": 0},
        stability_score=0.78,
        stress_results=[
            {"survived": True, "max_drawdown_pct": 0.08},
            {"survived": True, "max_drawdown_pct": 0.12},
            {"survived": False, "max_drawdown_pct": 0.25},
        ],
        overfit_diagnostic={"overfitting_score": 0.3, "is_overfit": False},
        governance={"status": "APPROVED", "deployment_stage": "PAPER", "deployment_cleared": True},
    )

    path = generator.save_report(report)

    from rich.table import Table
    t = Table(title="Validation Report", show_header=True, header_style="bold magenta")
    t.add_column("Section", style="cyan")
    t.add_column("Score", justify="right")
    t.add_column("Status")

    for name, section in report.sections.items():
        score = section.get("score", 0)
        status = section.get("status", "ok")
        style = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        t.add_row(name, f"[{style}]{score:.1f}[/{style}]", status)

    console.print(t)

    grade_map = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}
    grade_style = grade_map.get(report.overall_grade, "dim")
    console.print(
        f"\n  Overall Grade: [{grade_style}]{report.overall_grade}"
        f"[/{grade_style}]  Score: {report.overall_score:.1f}/100"
    )

    if report.warnings:
        for w in report.warnings:
            console.print(f"  [yellow]⚠ {w}[/yellow]")
    if report.failures:
        for f in report.failures:
            console.print(f"  [red]✗ {f}[/red]")

    console.print(f"\n[dim]Report saved: {path}[/dim]")


# ---------------------------------------------------------------------------
# bias-audit — Research Bias Audit
# ---------------------------------------------------------------------------

@main.command("bias-audit")
@click.option("--log-level", default="INFO", show_default=True)
def bias_audit_cmd(log_level: str):
    """Run a research bias audit on demo data."""
    _setup_logging(log_level)
    import numpy as np

    from .research.bias_audit import BiasAuditor

    console.print(Panel(
        "[bold cyan]RESEARCH BIAS AUDIT[/bold cyan]",
        title="ndbot", border_style="magenta"
    ))

    rng = np.random.default_rng(42)
    demo_returns = rng.normal(0.0005, 0.015, 500)
    demo_features = rng.normal(0, 1, (500, 5))

    auditor = BiasAuditor()
    result = auditor.audit(
        returns=demo_returns,
        features=demo_features,
        n_strategies_tested=10,
    )

    from rich.table import Table
    t = Table(
        title="Bias Audit Results",
        show_header=True, header_style="bold magenta",
    )
    t.add_column("Check", style="cyan")
    t.add_column("Passed", justify="center")
    t.add_column("Severity")

    for flag in result.flags:
        style = "red"
        symbol = "✗"
        t.add_row(flag.bias_type, f"[{style}]{symbol}[/{style}]", flag.severity)

    if not result.flags:
        t.add_row("All checks", "[green]✓[/green]", "none")

    console.print(t)
    console.print(
        f"\n  Passed: {result.checks_passed}  "
        f"Failed: {result.checks_failed}"
    )

    risk = result.bias_risk_score
    risk_style = "green" if risk < 0.3 else "yellow" if risk < 0.6 else "red"
    console.print(f"  Bias Risk Score: [{risk_style}]{risk:.3f}[/{risk_style}]")
    console.print(f"  Risk Level: {result.risk_level}")


# ---------------------------------------------------------------------------
# stress-test — Strategy Stress Testing
# ---------------------------------------------------------------------------

@main.command("stress-test")
@click.option("--log-level", default="INFO", show_default=True)
def stress_test_cmd(log_level: str):
    """Run strategy stress tests with predefined scenarios."""
    _setup_logging(log_level)
    import numpy as np

    from .research.stress_testing import StrategyStressTester

    console.print(Panel(
        "[bold cyan]STRATEGY STRESS TESTING[/bold cyan]",
        title="ndbot", border_style="magenta"
    ))

    rng = np.random.default_rng(42)
    demo_returns = rng.normal(0.0005, 0.015, 500)

    tester = StrategyStressTester()
    results = tester.run_all(demo_returns)

    from rich.table import Table
    t = Table(title="Stress Test Results", show_header=True, header_style="bold magenta")
    t.add_column("Scenario", style="cyan")
    t.add_column("Survived", justify="center")
    t.add_column("Max DD %", justify="right")
    t.add_column("Recovery Bars", justify="right")

    for r in results:
        style = "green" if r.survived else "red"
        symbol = "✓" if r.survived else "✗"
        t.add_row(
            r.scenario_name,
            f"[{style}]{symbol}[/{style}]",
            f"{r.max_drawdown_pct * 100:.1f}",
            str(r.recovery_bars),
        )

    console.print(t)
    survived_count = sum(1 for r in results if r.survived)
    console.print(f"\n  Survived: {survived_count}/{len(results)} scenarios")


# ---------------------------------------------------------------------------
# research-lab — Full Research Lab Demo
# ---------------------------------------------------------------------------

@main.command("research-lab")
@click.option("--log-level", default="INFO", show_default=True)
def research_lab_cmd(log_level: str):
    """Run full quant research lab demo pipeline."""
    _setup_logging(log_level)

    import numpy as np

    from .data.news_corpus import NewsCorpus
    from .features.event_embeddings import EventEmbeddingEngine
    from .portfolio.optimizer import PortfolioOptimizer
    from .portfolio.regime_strategy import RegimeStrategyEngine
    from .research.causal_analysis import CausalAnalysisEngine
    from .research.edge_decay import EdgeDecayMonitor
    from .research.signal_models import SignalModelEngine
    from .research.validation_report import ValidationReportGenerator
    from .simulation.market_simulator import MarketSimulator

    console.print(Panel(
        "[bold cyan]QUANT ALPHA RESEARCH LAB[/bold cyan]\n"
        "Full pipeline: corpus → embed → models → optimise → simulate",
        title="ndbot", border_style="magenta",
    ))
    rng = np.random.default_rng(42)

    # 1. Generate synthetic corpus
    console.print("\n[bold]1. News Corpus[/bold]")
    corpus = NewsCorpus()
    records = corpus.generate_synthetic_corpus(n_records=1000)
    corpus.ingest_records([r.to_dict() for r in records])
    stats = corpus.compute_stats()
    console.print(
        f"  Records: {stats.total_records} | "
        f"Sources: {stats.unique_sources} | "
        f"Domains: {len(stats.records_by_domain)}"
    )

    # 2. Event embeddings
    console.print("\n[bold]2. Event Embeddings[/bold]")
    embed = EventEmbeddingEngine(dim=32)
    headlines = [r.headline for r in records[:500]]
    embed.fit(headlines)
    similar = embed.find_similar("Oil prices surge after conflict", top_k=3)
    console.print(f"  Vocab: {embed.vocab_size} | Fitted: {embed.is_fitted}")
    for s in similar:
        console.print(f"  → sim={s.similarity:.3f}: {s.headline[:60]}")

    # 3. Causal analysis
    console.print("\n[bold]3. Causal Analysis[/bold]")
    causal = CausalAnalysisEngine()
    event_ret = rng.normal(0.002, 0.015, 100)
    ctrl_ret = rng.normal(0.0, 0.015, 200)
    report = causal.analyse(event_ret, ctrl_ret, event_type="SUPPLY_DISRUPTION")
    console.print(
        f"  Verdict: {report.verdict} | "
        f"Score: {report.composite_causal_score:.3f}"
    )
    for t in report.tests:
        sig = "[green]✓[/green]" if t.is_significant else "[red]✗[/red]"
        console.print(f"  {sig} {t.test_name}: p={t.p_value:.4f}")

    # 4. Signal models
    console.print("\n[bold]4. Multi-Model Comparison[/bold]")
    n_samples = 500
    features = rng.normal(0, 1, (n_samples, 8))
    returns = (
        0.3 * features[:, 0] + 0.2 * features[:, 1]
        + rng.normal(0, 0.5, n_samples)
    ) * 0.01
    engine = SignalModelEngine()
    model_report = engine.train_and_compare(
        features, returns,
        [f"f_{i}" for i in range(8)],
    )

    from rich.table import Table
    t = Table(
        title="Model Comparison",
        show_header=True, header_style="bold magenta",
    )
    t.add_column("Model", style="cyan")
    t.add_column("Sharpe", justify="right")
    t.add_column("Hit Rate", justify="right")
    for m in model_report.models:
        t.add_row(
            m.model_name,
            f"{m.sharpe_ratio:.3f}",
            f"{m.hit_rate * 100:.1f}%",
        )
    console.print(t)
    console.print(f"  Best: {model_report.best_model}")

    # 5. Portfolio optimization
    console.print("\n[bold]5. Portfolio Optimization[/bold]")
    opt = PortfolioOptimizer()
    asset_returns = rng.multivariate_normal(
        [0.001, 0.0008, 0.0012],
        np.diag([0.04, 0.05, 0.06]) * 0.01,
        size=252,
    )
    allocs = opt.compare_methods(asset_returns, ["BTC", "ETH", "SOL"])
    for a in allocs[:3]:
        console.print(
            f"  {a.method:<16} Sharpe={a.sharpe_ratio:+.3f}  "
            f"E[r]={a.expected_return * 100:+.2f}%"
        )

    # 6. Regime classification
    console.print("\n[bold]6. Regime Classification[/bold]")
    regime_eng = RegimeStrategyEngine()
    regime = regime_eng.classify_regime(
        rng.normal(0.0003, 0.015, 200),
        rng.lognormal(10, 1, 200),
    )
    adapt = regime_eng.get_adaptation(regime)
    console.print(
        f"  Vol={regime.volatility} Macro={regime.macro} "
        f"Liq={regime.liquidity}"
    )
    console.print(
        f"  Size={adapt.size_multiplier:.2f}x "
        f"Threshold={adapt.signal_threshold:.2f}"
    )

    # 7. Edge decay
    console.print("\n[bold]7. Edge Decay Monitor[/bold]")
    decay_mon = EdgeDecayMonitor()
    decaying = rng.normal(0.001, 0.01, 200) * np.linspace(1, 0.3, 200)
    decay_rpt = decay_mon.analyse("demo_signal", decaying)
    decay_style = {
        "active": "green", "warning": "yellow",
        "critical": "red", "dead": "red",
    }.get(decay_rpt.status, "dim")
    console.print(
        f"  Status: [{decay_style}]{decay_rpt.status}[/{decay_style}] | "
        f"Sharpe: {decay_rpt.current_sharpe:.3f} | "
        f"Decay: {decay_rpt.decay_pct:.1f}%"
    )

    # 8. Multi-agent simulation
    console.print("\n[bold]8. Multi-Agent Simulation[/bold]")
    sim = MarketSimulator(initial_price=100.0, seed=42)
    sim_result = sim.run(
        n_steps=300,
        event_schedule=[
            (30, 0.02), (80, -0.03), (150, 0.015), (220, -0.01),
        ],
    )
    console.print(
        f"  Steps: {sim_result.n_steps} | "
        f"Trades: {sim_result.n_trades} | "
        f"Events: {sim_result.events_injected}"
    )
    console.print(
        f"  News Trader PnL: {sim_result.news_trader_pnl:+.2f}"
    )

    # 9. Validation report
    console.print("\n[bold]9. Validation Report[/bold]")
    gen = ValidationReportGenerator()
    val = gen.generate(
        strategy_id="lab_demo",
        returns=rng.normal(0.0005, 0.015, 500),
        bias_audit={
            "bias_risk_score": 0.12,
            "risk_level": "low",
            "checks_failed": 0,
        },
        stability_score=0.82,
        stress_results=[
            {"survived": True, "max_drawdown_pct": 0.08},
            {"survived": True, "max_drawdown_pct": 0.12},
        ],
        governance={
            "status": "APPROVED",
            "deployment_stage": "PAPER",
            "deployment_cleared": True,
        },
    )
    grade_map = {
        "A": "green", "B": "green", "C": "yellow",
        "D": "red", "F": "red",
    }
    g_style = grade_map.get(val.overall_grade, "dim")
    console.print(
        f"  Grade: [{g_style}]{val.overall_grade}[/{g_style}] "
        f"Score: {val.overall_score:.1f}/100"
    )

    console.print(
        "\n[bold green]Research lab demo complete![/bold green]"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config_or_exit(path: str) -> BotConfig:
    try:
        return load_config(path)
    except FileNotFoundError as e:
        console.print(f"[bold red]Config not found:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Config error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
