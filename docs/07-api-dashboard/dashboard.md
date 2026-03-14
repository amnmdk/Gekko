# Dashboard Guide

The web dashboard provides a real-time view of the trading system.

Access: `http://localhost:80` (via Docker) or `http://localhost:8000` (direct backend)

---

## Layout

### Top Bar
- **Logo**: ndbot branding
- **Price Tickers**: BTC/USDT and ETH/USDT with up/down indicators
- **Connection Status**: Green dot = connected, red = disconnected
- **Portfolio Stats**: Balance, PnL, trade count

### Left Panel
- **Map Controls**: Toggle layers (ENERGY_GEO markers, AI_RELEASES markers, positions, trade history)
- **Portfolio Summary**: Balance, PnL %, drawdown
- **Equity Chart**: Canvas-rendered equity curve
- **Legend**: Colour coding for event types

### Centre
- **Leaflet Map**: Dark CartoDB basemap with event markers
  - Red/orange markers = ENERGY_GEO events
  - Purple markers = AI_RELEASES events
  - Green markers = LONG positions
  - Red markers = SHORT positions

### Right Panel
- **Live Event Feed**: Scrolling list of recent news events with domain tags

### Bottom Panel
- **Trade History Table**: Time, Symbol, Direction, Entry, Exit, Size, PnL, Status, Event headline
- **Colour-coded PnL**: Green for profits, red for losses

### News Ticker
- Breaking events scroll across the bottom of the screen

---

## Settings Modal

Click the gear icon to open runtime settings:

| Setting | Range | Effect |
|---|---|---|
| Initial Capital | $10 – $100,000 | Reset balance |
| Tick Speed | 5s – 300s | Engine update frequency |
| Risk % | 0.1% – 10% | Risk per trade |
| Min Confidence | 0% – 100% | Signal threshold |
| Max Positions | 1 – 10 | Concurrent position limit |

Changes take effect immediately via `PATCH /api/config`.

---

## Real-time Updates

The dashboard connects via WebSocket to `ws://localhost:8000/ws`:

1. **On connect**: Receives full `snapshot` with all current state
2. **On tick**: Receives `update` with latest prices, positions, events
3. **On config change**: Receives `config_update`
4. **On reset**: Receives `reset` and refreshes all panels

If the WebSocket disconnects, the dashboard shows a red indicator and attempts to reconnect automatically.

---

## Technologies

| Component | Technology |
|---|---|
| Map | Leaflet.js with CartoDB dark basemap |
| Chart | Vanilla Canvas 2D API |
| WebSocket | Native browser WebSocket API |
| REST calls | Fetch API |
| Styling | CSS custom properties (dark theme) |

No build step required — plain HTML/JS/CSS served by nginx.
