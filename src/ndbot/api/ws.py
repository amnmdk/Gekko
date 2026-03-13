"""WebSocket endpoint — pushes real-time updates to the frontend."""
from __future__ import annotations

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .state import AppState

logger = logging.getLogger(__name__)
ws_router = APIRouter()
_state: AppState | None = None


def init_ws(state: AppState) -> None:
    global _state
    _state = state


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if _state is None:
        await websocket.close(code=1011)
        return

    _state.add_ws_client(websocket)
    logger.info("WS client connected. Total=%d", len(_state._ws_clients))

    # Send current state snapshot on connect
    try:
        await websocket.send_json({
            "type": "snapshot",
            "data": {
                "summary": _state.summary(),
                "events": [e.to_dict() for e in _state.events[:50]],
                "positions": [p.to_dict() for p in _state.open_positions.values()],
                "trades": [t.to_dict() for t in _state.trades[:50]],
            },
        })

        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    except Exception as exc:
        logger.warning("WS error: %s", exc)
    finally:
        _state.remove_ws_client(websocket)
