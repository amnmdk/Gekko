"""
FastAPI application entry point.

Starts the mock trading engine as a background asyncio task
and mounts REST + WebSocket routes.

Run with:
    uvicorn src.ndbot.api.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .engine import MockTradingEngine
from .routes import init_routes, router
from .state import AppState
from .ws import init_ws, ws_router


def _setup_logging(log_level: str = "INFO") -> None:
    """
    Configure root logger with:
      - Console handler (coloured via uvicorn, plain otherwise)
      - Rotating file handler → logs/ndbot.log (5 MB × 3 backups)

    Safe to call multiple times; handlers are only added once.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    root = logging.getLogger()

    if root.handlers:
        # Already configured (e.g. pytest captures logging)
        root.setLevel(level)
        return

    root.setLevel(level)

    # Console
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt))
    root.addHandler(console)

    # Rotating file — goes to logs/ndbot.log (volume-mounted in Docker)
    try:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "ndbot.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(file_handler)
    except OSError:
        # Read-only filesystem (e.g. some CI environments) — skip file handler
        pass


_setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared application state
# ---------------------------------------------------------------------------
state = AppState(initial_capital=500.0)
engine = MockTradingEngine(state=state, tick_interval=25.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: launch trading engine in background
    task = asyncio.create_task(engine.run())
    logger.info("ndbot API started — trading engine running")
    yield
    # Shutdown: stop engine
    engine.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("ndbot API stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ndbot Trading Dashboard API",
    description="News-Driven Intraday Trading Research Framework",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up shared state to routes + ws
init_routes(state)
init_ws(state)

app.include_router(router, prefix="/api")
app.include_router(ws_router)

# Alpha discovery dashboard routes
try:
    from ..research.alpha_routes import alpha_router, init_alpha_routes
    init_alpha_routes()
    app.include_router(alpha_router, prefix="/api")
except ImportError:
    pass  # Alpha modules not available

# Serve frontend static files if available (for single-command launch)
try:
    from fastapi.staticfiles import StaticFiles
    frontend_dir = Path(__file__).resolve().parents[3] / "frontend"
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True))
except Exception:
    pass
