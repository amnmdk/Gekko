# REST API Reference

Base URL: `http://localhost:8000/api/`

All endpoints return JSON.

---

## Endpoints

### `GET /api/health`

Health check endpoint. Used by Docker healthcheck and monitoring.

**Response**:
```json
{
  "status": "ok",
  "running": true,
  "balance": 100.00
}
```

---

### `GET /api/status`

Full system status summary.

**Response**:
```json
{
  "balance": 102.34,
  "initial_capital": 100.0,
  "total_pnl": 2.34,
  "total_pnl_pct": 2.34,
  "peak_balance": 105.0,
  "drawdown_pct": 2.53,
  "total_trades": 15,
  "winning_trades": 9,
  "open_positions": 1,
  "running": true,
  "uptime_seconds": 3600
}
```

---

### `GET /api/balance`

Current balance and PnL summary.

**Response**:
```json
{
  "balance": 102.34,
  "initial_capital": 100.0,
  "total_pnl": 2.34,
  "total_pnl_pct": 2.34,
  "peak_balance": 105.0,
  "drawdown_pct": 2.53,
  "currency": "EUR"
}
```

---

### `GET /api/events`

Recent news events.

**Query Parameters**:
| Param | Type | Default | Range | Description |
|---|---|---|---|---|
| `limit` | int | 50 | 1–200 | Max events to return |

**Response**: Array of event objects.

---

### `GET /api/positions`

Currently open positions.

**Response**: Array of position objects with entry price, size, SL, TP, unrealised PnL.

---

### `GET /api/trades`

Closed trade history.

**Query Parameters**:
| Param | Type | Default | Range |
|---|---|---|---|
| `limit` | int | 100 | 1–500 |

**Response**: Array of closed trade objects with PnL, close reason, timestamps.

---

### `GET /api/prices`

Current simulated/live prices.

**Response**:
```json
{
  "BTC/USDT": 45000.00,
  "ETH/USDT": 2500.00
}
```

---

### `GET /api/equity-curve`

Balance history for charting.

**Query Parameters**:
| Param | Type | Default | Range |
|---|---|---|---|
| `limit` | int | 200 | 1–1000 |

**Response**: Array of `{ts, balance}` objects.

---

### `GET /api/metrics`

Detailed performance metrics.

**Response**:
```json
{
  "balance": 102.34,
  "total_trades": 15,
  "gross_profit": 5.67,
  "gross_loss": 3.33,
  "profit_factor": 1.703,
  "avg_win": 0.63,
  "avg_loss": -0.55,
  "largest_win": 1.23,
  "largest_loss": -0.89,
  "total_pnl_sum": 2.34
}
```

---

### `PATCH /api/config`

Update runtime trading parameters without restart.

**Request Body**:
```json
{
  "tick_interval": 30.0,
  "risk_pct": 0.02,
  "min_confidence": 0.50,
  "max_positions": 5
}
```

All fields optional. Values are clamped to valid ranges:
| Field | Min | Max |
|---|---|---|
| `tick_interval` | 5.0 | 300.0 |
| `risk_pct` | 0.001 | 0.10 |
| `min_confidence` | 0.0 | 1.0 |
| `max_positions` | 1 | 10 |

**Response**:
```json
{
  "message": "Config updated",
  "config": { ... }
}
```

---

### `POST /api/reset`

Reset bot to new starting capital. Clears all trade history.

**Query Parameters**:
| Param | Type | Default | Range |
|---|---|---|---|
| `capital` | float | 500.0 | 10.0–100,000.0 |

**Response**:
```json
{
  "message": "Bot reset. New balance: 500.00 EUR"
}
```
