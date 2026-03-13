// ============================================================
// NDBOT Trading Dashboard — Main JavaScript
// Leaflet.js map + WebSocket real-time updates
// ============================================================

const API_BASE = window.location.origin + "/api";
const WS_URL   = (window.location.protocol === "https:" ? "wss:" : "ws:") +
                 "//" + window.location.host + "/ws";

// ── State ────────────────────────────────────────────────────
const state = {
  ws: null,
  connected: false,
  events: [],
  positions: [],
  trades: [],
  summary: null,
  layers: {
    energyEvents: true,
    aiEvents:     true,
    openPositions: true,
    tradeHistory: true,
  },
};

// ── Map setup ─────────────────────────────────────────────────
const map = L.map("map", {
  center: [20, 10],
  zoom: 2.5,
  zoomControl: false,
  attributionControl: false,
});

L.tileLayer(
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  { subdomains: "abcd", maxZoom: 19 }
).addTo(map);

L.control.zoom({ position: "topright" }).addTo(map);

// Layer groups
const layerGroups = {
  energyEvents:  L.layerGroup().addTo(map),
  aiEvents:      L.layerGroup().addTo(map),
  openPositions: L.layerGroup().addTo(map),
  tradeHistory:  L.layerGroup().addTo(map),
};

// ── Helpers ───────────────────────────────────────────────────
function fmtEur(v) {
  const sign = v >= 0 ? "+" : "";
  return sign + v.toFixed(2) + " €";
}
function fmtPct(v) {
  const sign = v >= 0 ? "+" : "";
  return sign + v.toFixed(2) + "%";
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function domainClass(domain) {
  return domain === "ENERGY_GEO" ? "energy" : "ai";
}
function dirClass(dir) {
  if (dir === "LONG")  return "long";
  if (dir === "SHORT") return "short";
  return "neutral";
}

// ── Custom Leaflet icons ──────────────────────────────────────
function makeIcon(cssClass) {
  return L.divIcon({ className: "", html: `<div class="${cssClass}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });
}

// ── Map markers ───────────────────────────────────────────────
const markerCache = {};   // event id → marker

function addEventMarker(ev) {
  if (!state.layers.energyEvents && ev.domain === "ENERGY_GEO") return;
  if (!state.layers.aiEvents     && ev.domain === "AI_RELEASES") return;

  const iconClass = ev.domain === "ENERGY_GEO" ? "marker-energy" : "marker-ai";
  const layer = ev.domain === "ENERGY_GEO" ? layerGroups.energyEvents : layerGroups.aiEvents;
  const marker = L.marker([ev.lat, ev.lon], { icon: makeIcon(iconClass) });

  const dirLabel = ev.direction !== "NEUTRAL"
    ? `<span class="ev-direction ${dirClass(ev.direction)}">${ev.direction}</span>`
    : "";
  marker.bindPopup(`
    <div class="popup-headline">${ev.headline}</div>
    <div class="popup-meta">
      <span class="ev-domain ${domainClass(ev.domain)}">${ev.domain}</span>
      ${dirLabel}
      <span class="popup-conf">conf ${(ev.confidence * 100).toFixed(0)}%</span>
      <span>${fmtTime(ev.timestamp)}</span>
    </div>
  `);
  marker.addTo(layer);
  markerCache[ev.id] = { marker, layerKey: ev.domain === "ENERGY_GEO" ? "energyEvents" : "aiEvents" };

  // Auto-remove old markers (keep last 30 per domain)
  const markers = Object.values(markerCache);
  const domainMarkers = markers.filter(m => m.layerKey === markerCache[ev.id]?.layerKey);
  if (domainMarkers.length > 30) {
    // Remove oldest entry from cache (approximate)
    const oldest = domainMarkers[0];
    oldest.marker.remove();
  }
}

const positionMarkers = {};

function refreshPositionMarkers(positions) {
  // Clear existing
  Object.values(positionMarkers).forEach(m => m.remove());
  Object.keys(positionMarkers).forEach(k => delete positionMarkers[k]);

  if (!state.layers.openPositions) return;

  positions.forEach(pos => {
    const marker = L.marker([pos.lat, pos.lon], { icon: makeIcon("marker-position") });
    const pnlStr = fmtEur(pos.pnl_eur);
    const pnlClass = pos.pnl_eur >= 0 ? "pnl-pos" : "pnl-neg";
    marker.bindPopup(`
      <div class="popup-headline">${pos.symbol} — ${pos.direction}</div>
      <div class="popup-meta">
        <span>Entry: ${pos.entry_price}</span>
        <span class="${pnlClass}">PnL: ${pnlStr}</span>
        <span>Size: ${pos.size_eur.toFixed(2)} €</span>
      </div>
    `);
    marker.addTo(layerGroups.openPositions);
    positionMarkers[pos.id] = marker;
  });
}

// ── Top bar updates ───────────────────────────────────────────
function updateTopBar(s) {
  if (!s) return;
  const el = id => document.getElementById(id);

  const pnl = s.total_pnl;
  const pnlPct = s.total_pnl_pct;
  el("tb-balance").textContent = s.balance.toFixed(2) + " €";
  el("tb-pnl").textContent = fmtEur(pnl);
  el("tb-pnl").className = "value " + (pnl >= 0 ? "pos" : "neg");
  el("tb-pnlpct").textContent = fmtPct(pnlPct);
  el("tb-pnlpct").className = "value " + (pnlPct >= 0 ? "pos" : "neg");
  el("tb-trades").textContent = s.total_trades;
  el("tb-winrate").textContent = s.win_rate + "%";
  el("tb-drawdown").textContent = s.drawdown_pct.toFixed(1) + "%";
  el("tb-open").textContent = s.open_positions;
}

// ── Left panel stats ──────────────────────────────────────────
function updateLeftPanel(s) {
  if (!s) return;
  document.getElementById("lp-balance").textContent = s.balance.toFixed(2) + " €";
  document.getElementById("lp-pnl").textContent = fmtEur(s.total_pnl);
  document.getElementById("lp-pnl").className = "s-value " + (s.total_pnl >= 0 ? "pnl-pos" : "pnl-neg");
  document.getElementById("lp-dd").textContent = s.drawdown_pct.toFixed(1) + "%";
  document.getElementById("lp-wr").textContent = s.win_rate + "%";
  document.getElementById("lp-trades").textContent = s.total_trades;
}

// ── Events list ───────────────────────────────────────────────
function renderEvents(events) {
  const list = document.getElementById("events-list");
  const items = events.slice(0, 40).map(ev => {
    const dc = domainClass(ev.domain);
    const dir = ev.direction !== "NEUTRAL" ? `<span class="ev-direction ${dirClass(ev.direction)}">${ev.direction}</span>` : "";
    return `<div class="event-item" data-id="${ev.id}" onclick="panToEvent('${ev.id}')">
      <span class="ev-domain ${dc}">${ev.domain === "ENERGY_GEO" ? "GEO" : "AI"}</span>
      <div class="ev-headline">${ev.headline}</div>
      <div class="ev-meta">
        ${dir}
        <span>${(ev.confidence * 100).toFixed(0)}% conf</span>
        <span>${fmtTime(ev.timestamp)}</span>
      </div>
    </div>`;
  }).join("");
  list.innerHTML = items || "<div style='padding:14px;color:var(--text-muted);font-size:12px'>Waiting for events…</div>";
}

window.panToEvent = function(id) {
  const ev = state.events.find(e => e.id === id);
  if (ev) map.flyTo([ev.lat, ev.lon], 5, { duration: 1.2 });
};

// ── Trades table ──────────────────────────────────────────────
function renderTrades(trades, positions) {
  const openCount = positions.length;
  document.getElementById("open-count-badge").textContent = openCount + " OPEN";

  const allRows = [
    ...positions.map(t => ({ ...t, status: "OPEN" })),
    ...trades.slice(0, 40),
  ];

  const rows = allRows.map(t => {
    const pnlClass = t.pnl_eur >= 0 ? "pnl-pos" : "pnl-neg";
    const statusCls = (t.status || "open").toLowerCase().replace("_", "_");
    return `<tr>
      <td>${fmtTime(t.opened_at)}</td>
      <td>${t.symbol}</td>
      <td class="${dirClass(t.direction)}" style="font-weight:700">${t.direction}</td>
      <td>${t.entry_price.toLocaleString()}</td>
      <td>${t.exit_price ? t.exit_price.toLocaleString() : "—"}</td>
      <td>${t.size_eur.toFixed(2)} €</td>
      <td class="${pnlClass}">${fmtEur(t.pnl_eur)}</td>
      <td><span class="status-badge ${statusCls}">${t.status}</span></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)">${t.event_headline}</td>
    </tr>`;
  }).join("");

  const tbody = document.querySelector("#trades-table tbody");
  tbody.innerHTML = rows || "<tr><td colspan='9' style='color:var(--text-muted);padding:10px'>No trades yet</td></tr>";
}

// ── Ticker ────────────────────────────────────────────────────
function rebuildTicker(events) {
  const inner = document.getElementById("ticker-inner");
  const items = events.slice(0, 20).map(ev => {
    const prefix = ev.domain === "ENERGY_GEO" ? "⚡" : "🤖";
    return `<span>${prefix} <span class="ticker-hl">${ev.headline}</span></span>`;
  });
  // Duplicate for seamless loop
  inner.innerHTML = [...items, ...items].join("");
}

// ── Toast notifications ───────────────────────────────────────
function showToast(msg, cls) {
  const c = document.getElementById("toast-container");
  const div = document.createElement("div");
  div.className = "toast " + cls;
  div.innerHTML = msg;
  c.appendChild(div);
  setTimeout(() => div.remove(), 4000);
}

// ── Connection status ─────────────────────────────────────────
function setConnected(yes) {
  state.connected = yes;
  const dot = document.getElementById("status-dot");
  const lbl = document.getElementById("status-label");
  dot.className = "status-dot" + (yes ? "" : " offline");
  lbl.textContent = yes ? "LIVE" : "RECONNECTING";
}

// ── WebSocket ─────────────────────────────────────────────────
function connectWS() {
  const ws = new WebSocket(WS_URL);
  state.ws = ws;

  ws.onopen = () => {
    setConnected(true);
    // Keep-alive ping every 20 s
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      else clearInterval(ping);
    }, 20000);
  };

  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    setConnected(false);
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

function handleMessage(msg) {
  switch (msg.type) {

    case "snapshot":
      state.summary   = msg.data.summary;
      state.events    = msg.data.events;
      state.positions = msg.data.positions;
      state.trades    = msg.data.trades;
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      renderEvents(state.events);
      renderTrades(state.trades, state.positions);
      refreshPositionMarkers(state.positions);
      state.events.forEach(addEventMarker);
      rebuildTicker(state.events);
      break;

    case "event": {
      const ev = msg.data;
      state.events.unshift(ev);
      state.events = state.events.slice(0, 200);
      addEventMarker(ev);
      renderEvents(state.events);
      rebuildTicker(state.events);
      break;
    }

    case "trade_open": {
      const t = msg.data;
      state.positions.push(t);
      refreshPositionMarkers(state.positions);
      renderTrades(state.trades, state.positions);
      const dir = t.direction;
      showToast(`📈 OPEN ${dir} ${t.symbol}<br>${t.size_eur.toFixed(2)} € @ ${t.entry_price}`, "trade-open");
      break;
    }

    case "trade_close": {
      const t = msg.data;
      state.positions = state.positions.filter(p => p.id !== t.id);
      state.trades.unshift(t);
      state.trades = state.trades.slice(0, 500);
      refreshPositionMarkers(state.positions);
      renderTrades(state.trades, state.positions);
      const cls = t.pnl_eur >= 0 ? "trade-close" : "trade-loss";
      const icon = t.status === "TP_HIT" ? "🎯" : t.status === "SL_HIT" ? "🛑" : "⏱";
      showToast(`${icon} ${t.status} ${t.direction} ${t.symbol}<br><strong>${fmtEur(t.pnl_eur)}</strong>`, cls);
      break;
    }

    case "positions_update": {
      state.positions = msg.data;
      refreshPositionMarkers(state.positions);
      renderTrades(state.trades, state.positions);
      break;
    }

    case "balance_update":
      state.summary = msg.data;
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      break;

    case "reset":
      state.summary   = msg.data;
      state.events    = [];
      state.positions = [];
      state.trades    = [];
      Object.values(layerGroups).forEach(lg => lg.clearLayers());
      renderEvents([]);
      renderTrades([], []);
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      showToast("🔄 Bot reset — new balance: " + state.summary.balance.toFixed(2) + " €", "trade-open");
      break;
  }
}

// ── Layer toggle wiring ───────────────────────────────────────
function initLayerToggles() {
  const toggles = {
    "toggle-energy":    ["energyEvents"],
    "toggle-ai":        ["aiEvents"],
    "toggle-positions": ["openPositions"],
    "toggle-trades":    ["tradeHistory"],
  };

  Object.entries(toggles).forEach(([id, keys]) => {
    const cb = document.getElementById(id);
    if (!cb) return;
    cb.addEventListener("change", () => {
      keys.forEach(k => {
        state.layers[k] = cb.checked;
        if (cb.checked) {
          layerGroups[k].addTo(map);
        } else {
          map.removeLayer(layerGroups[k]);
        }
      });
    });
  });
}

// ── Reset button ──────────────────────────────────────────────
document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("Reset bot to €500 starting balance?")) return;
  await fetch(API_BASE + "/reset?capital=500", { method: "POST" });
});

// ── Clock ─────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById("clock").textContent =
    now.toUTCString().replace(" GMT", " UTC");
}
setInterval(updateClock, 1000);
updateClock();

// ── Init ──────────────────────────────────────────────────────
initLayerToggles();
connectWS();
