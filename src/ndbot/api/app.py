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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .engine import MockTradingEngine
from .routes import init_routes, router
from .state import AppState
from .ws import init_ws, ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
