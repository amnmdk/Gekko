# WebSocket API

Endpoint: `ws://localhost:8000/ws`

---

## Connection

Connect via any WebSocket client:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log(msg.type, msg.data);
};
```

---

## Messages

### `snapshot` (sent on connect)

Immediately after connection, the server sends the full current state:

```json
{
  "type": "snapshot",
  "data": {
    "summary": {
      "balance": 102.34,
      "initial_capital": 100.0,
      "total_pnl": 2.34,
      "open_positions": 1,
      "total_trades": 15
    },
    "events": [...],
    "positions": [...],
    "trades": [...],
    "equity_curve": [...],
    "prices": {
      "BTC/USDT": 45000.00
    }
  }
}
```

### `update` (periodic)

Sent on each trading engine tick (every `tick_interval` seconds):

```json
{
  "type": "update",
  "data": {
    "summary": { ... },
    "events": [...],
    "positions": [...],
    "trades": [...],
    "equity_curve": [...],
    "prices": { ... }
  }
}
```

### `config_update` (on config change)

Sent when `/api/config` PATCH is called:

```json
{
  "type": "config_update",
  "data": {
    "tick_interval": 30.0,
    "risk_pct": 0.02,
    "min_confidence": 0.50,
    "max_positions": 5
  }
}
```

### `reset` (on bot reset)

Sent when `/api/reset` POST is called:

```json
{
  "type": "reset",
  "data": {
    "balance": 500.0,
    "initial_capital": 500.0,
    "total_pnl": 0.0,
    "total_trades": 0
  }
}
```

---

## Frontend Integration

The dashboard (`frontend/js/main.js`) uses the WebSocket for:
- Real-time price ticker updates
- Live equity curve chart redraw
- Event feed with new event notifications
- Position table updates
- Trade history updates
- Toast notifications on new trades
