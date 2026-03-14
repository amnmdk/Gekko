"""
REST API and WebSocket integration tests.

Uses FastAPI TestClient (starlette) — fully synchronous, no internet required.
Each test gets a fresh app instance (scope=function) to avoid state leakage.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Create a fresh TestClient per test (starts lifespan → engine)."""
    from ndbot.api.app import app

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health & Status
# ---------------------------------------------------------------------------


def test_api_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "running" in data
    assert "balance" in data
    assert data["balance"] > 0


def test_api_status(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "balance" in data
    assert "total_trades" in data
    assert "running" in data


def test_api_balance(client: TestClient) -> None:
    resp = client.get("/api/balance")
    assert resp.status_code == 200
    data = resp.json()
    assert "balance" in data
    assert data["balance"] > 0
    assert "drawdown_pct" in data
    assert "total_pnl" in data


# ---------------------------------------------------------------------------
# Events / Positions / Trades
# ---------------------------------------------------------------------------


def test_api_events_returns_list(client: TestClient) -> None:
    resp = client.get("/api/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_events_limit_query(client: TestClient) -> None:
    resp = client.get("/api/events?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) <= 3


def test_api_events_limit_invalid(client: TestClient) -> None:
    """limit=0 is below minimum — expect 422 Unprocessable Entity."""
    resp = client.get("/api/events?limit=0")
    assert resp.status_code == 422


def test_api_positions_returns_list(client: TestClient) -> None:
    resp = client.get("/api/positions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_trades_returns_list(client: TestClient) -> None:
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_trades_limit_query(client: TestClient) -> None:
    resp = client.get("/api/trades?limit=10")
    assert resp.status_code == 200
    assert len(resp.json()) <= 10


# ---------------------------------------------------------------------------
# Prices & Equity Curve
# ---------------------------------------------------------------------------


def test_api_prices_structure(client: TestClient) -> None:
    resp = client.get("/api/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert "BTC/USDT" in data
    assert "ETH/USDT" in data
    assert data["BTC/USDT"] > 0
    assert data["ETH/USDT"] > 0


def test_api_equity_curve_structure(client: TestClient) -> None:
    resp = client.get("/api/equity-curve")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # At least initial balance entry
    assert "ts" in data[0]
    assert "balance" in data[0]
    assert data[0]["balance"] > 0


def test_api_equity_curve_limit(client: TestClient) -> None:
    resp = client.get("/api/equity-curve?limit=5")
    assert resp.status_code == 200
    assert len(resp.json()) <= 5


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_api_metrics_returns_dict(client: TestClient) -> None:
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    # Summary keys are always present (from s.summary())
    assert "total_trades" in data
    assert "win_rate" in data
    assert "balance" in data


# ---------------------------------------------------------------------------
# Config PATCH
# ---------------------------------------------------------------------------


def test_api_config_patch_tick_interval(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"tick_interval": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data
    assert data["config"]["tick_interval"] == pytest.approx(10.0)


def test_api_config_patch_tick_interval_clamped(client: TestClient) -> None:
    """Values outside [5, 300] must be clamped, not rejected."""
    resp = client.patch("/api/config", json={"tick_interval": 99999.0})
    assert resp.status_code == 200
    assert resp.json()["config"]["tick_interval"] <= 300.0


def test_api_config_patch_tick_interval_floor(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"tick_interval": 0.001})
    assert resp.status_code == 200
    assert resp.json()["config"]["tick_interval"] >= 5.0


def test_api_config_patch_risk_pct(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"risk_pct": 0.03})
    assert resp.status_code == 200
    assert resp.json()["config"]["risk_pct"] == pytest.approx(0.03)


def test_api_config_patch_min_confidence(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"min_confidence": 0.55})
    assert resp.status_code == 200
    assert resp.json()["config"]["min_confidence"] == pytest.approx(0.55)


def test_api_config_patch_max_positions(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"max_positions": 5})
    assert resp.status_code == 200
    assert resp.json()["config"]["max_positions"] == 5


def test_api_config_patch_max_positions_clamped(client: TestClient) -> None:
    resp = client.patch("/api/config", json={"max_positions": 999})
    assert resp.status_code == 200
    assert resp.json()["config"]["max_positions"] <= 10


def test_api_config_patch_empty_body(client: TestClient) -> None:
    """Empty PATCH should return 200 with unchanged config."""
    resp = client.patch("/api/config", json={})
    assert resp.status_code == 200
    assert "config" in resp.json()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_api_reset_custom_capital(client: TestClient) -> None:
    resp = client.post("/api/reset?capital=300.0")
    assert resp.status_code == 200
    assert "message" in resp.json()

    # Verify via /balance
    bal_resp = client.get("/api/balance")
    assert bal_resp.json()["balance"] == pytest.approx(300.0)


def test_api_reset_default_capital(client: TestClient) -> None:
    resp = client.post("/api/reset")
    assert resp.status_code == 200
    bal = client.get("/api/balance").json()["balance"]
    assert bal > 0  # Default capital (500.0)


def test_api_reset_clears_trades(client: TestClient) -> None:
    """After reset, closed trades list should be empty."""
    client.post("/api/reset?capital=500.0")
    trades = client.get("/api/trades").json()
    assert trades == []


def test_api_reset_below_minimum(client: TestClient) -> None:
    """Capital below minimum (10.0) should return 422."""
    resp = client.post("/api/reset?capital=0.5")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


def test_api_websocket_snapshot(client: TestClient) -> None:
    """On connect, server must immediately send a snapshot message."""
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "snapshot"
    snap = msg["data"]
    assert "summary" in snap
    assert "events" in snap
    assert "positions" in snap
    assert "trades" in snap
    assert "equity_curve" in snap
    assert "prices" in snap
    # Summary sub-structure
    assert "balance" in snap["summary"]
    assert "total_trades" in snap["summary"]
