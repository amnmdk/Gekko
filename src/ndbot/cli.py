"""
ndbot CLI — entry point for all commands.

Commands
--------
  simulate    Run event-driven simulation with synthetic data
  backtest    Replay stored events + candles
  event-study Run event study analysis
  walkforward Run walk-forward validation
  grid        Parameter grid search
  paper       Run paper trading (sandbox/testnet only)
  status      Show recent runs and system status
  seed-demo   Generate demo data and run a quick simulation
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
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

from . import __version__
from .config.loader import load_config
from .config.settings import BotConfig
from .metrics import (
    print_event_table,
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
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stdout,
    )
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

    from .storage.database import Database
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

    from .storage.database import Database
    from .execution.simulate import SimulationEngine
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .market.regime import RegimeDetector

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

    engine = SimulationEngine(cfg, db, n_events=40, n_candles=500, seed=seed)
    if events_list:
        engine._market.load_dataframe(candles_df)
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

    from .storage.database import Database
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .market.regime import RegimeDetector
    from .feeds.synthetic import SyntheticFeed
    from .feeds.base import EventDomain
    from .research.event_study import EventStudy
    from .classifier.keyword_classifier import KeywordClassifier

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

    from .storage.database import Database
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .market.regime import RegimeDetector
    from .feeds.synthetic import SyntheticFeed
    from .feeds.base import EventDomain
    from .research.walkforward import WalkForwardValidator
    from .classifier.keyword_classifier import KeywordClassifier
    from datetime import datetime, timedelta, timezone

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
        f"Train: {cfg.research.train_days}d | Test: {cfg.research.test_days}d | Step: {cfg.research.step_days}d\n"
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
        console.print(f"\n[bold]Aggregate OOS Metrics[/bold]")
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

    from .storage.database import Database
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .market.regime import RegimeDetector
    from .feeds.synthetic import SyntheticFeed
    from .feeds.base import EventDomain
    from .classifier.keyword_classifier import KeywordClassifier
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
    console.print(f"\n[bold green]Best params: {best_params} | Sharpe={best_sharpe:.4f}[/bold green]")
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

    from .storage.database import Database
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
    from .storage.database import Database

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

    import tempfile, yaml
    from .config.settings import BotConfig, SignalConfig, FeedConfig

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
    from datetime import datetime, timezone
    run_id_seed = hashlib.sha256(f"seed-demo{seed}".encode()).hexdigest()[:8]
    db_path = f"data/demo_{run_id_seed}.db"
    cfg = cfg.model_copy(update={"storage": cfg.storage.model_copy(update={"db_path": db_path})})

    from .storage.database import Database
    from .execution.simulate import SimulationEngine

    db = Database(cfg.storage.db_path)
    db.init()

    engine = SimulationEngine(cfg, db, n_events=30, n_candles=600, seed=seed)
    summary = engine.run()
    print_performance_table(summary, title="Demo Simulation Results")

    # Event study
    from .feeds.synthetic import SyntheticFeed
    from .feeds.base import EventDomain
    from .market.synthetic_candles import SyntheticCandleGenerator
    from .market.regime import RegimeDetector
    from .classifier.keyword_classifier import KeywordClassifier
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
    report = study.run(
        events=[ev.to_dict() for ev in all_events],
        output_dir=output_dir,
        run_name="seed-demo",
    )

    console.print(f"\n[bold green]Demo complete![/bold green]")
    console.print(f"  Simulation DB:  {cfg.storage.db_path}")
    console.print(f"  Event study:    {output_dir}/event_study_seed-demo_*.png")
    console.print(f"\n[dim]Run 'ndbot status' to see all runs.[/dim]")


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
