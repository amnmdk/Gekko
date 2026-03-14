// ============================================================
// NDBOT Trading Dashboard — Main JavaScript
// Leaflet map + WebSocket real-time + Chart.js equity curve
// ============================================================

const API_BASE = window.location.origin + "/api";
const WS_URL   = (window.location.protocol === "https:" ? "wss:" : "ws:") +
                 "//" + window.location.host + "/ws";

// ── App state ─────────────────────────────────────────────────────────────
const state = {
  ws: null,
  connected: false,
  events: [],
  positions: [],
  trades: [],
  summary: null,
  equityCurve: [],
  prices: {},
  prevPrices: {},
  layers: { energyEvents: true, aiEvents: true, openPositions: true, tradeHistory: true },
};

// ── Map ───────────────────────────────────────────────────────────────────
const map = L.map("map", { center: [20, 10], zoom: 2.5, zoomControl: false, attributionControl: false });
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  { subdomains: "abcd", maxZoom: 19 }).addTo(map);
L.control.zoom({ position: "topright" }).addTo(map);

const layerGroups = {
  energyEvents:  L.layerGroup().addTo(map),
  aiEvents:      L.layerGroup().addTo(map),
  openPositions: L.layerGroup().addTo(map),
  tradeHistory:  L.layerGroup().addTo(map),
};

// ── Equity chart (vanilla Canvas — no extra CDN needed) ──────────────────
const equityCanvas = document.getElementById("equity-chart");
const equityCtx    = equityCanvas ? equityCanvas.getContext("2d") : null;

function drawEquityChart(curve) {
  if (!equityCtx || !curve || curve.length < 2) return;

  const W = equityCanvas.offsetWidth || 192;
  const H = 80;
  equityCanvas.width  = W;
  equityCanvas.height = H;

  const values = curve.map(p => p.balance);
  const initial = values[0];
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;

  const toY = v => H - 4 - ((v - minV) / range) * (H - 8);
  const toX = (i) => (i / (values.length - 1)) * W;

  equityCtx.clearRect(0, 0, W, H);

  // Gradient fill
  const isProfit = values[values.length - 1] >= initial;
  const gradColor = isProfit ? "#22c55e" : "#ef4444";
  const grad = equityCtx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, isProfit ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)");
  grad.addColorStop(1, "rgba(0,0,0,0)");

  equityCtx.beginPath();
  equityCtx.moveTo(toX(0), toY(values[0]));
  for (let i = 1; i < values.length; i++) equityCtx.lineTo(toX(i), toY(values[i]));
  equityCtx.lineTo(toX(values.length - 1), H);
  equityCtx.lineTo(toX(0), H);
  equityCtx.closePath();
  equityCtx.fillStyle = grad;
  equityCtx.fill();

  // Line
  equityCtx.beginPath();
  equityCtx.moveTo(toX(0), toY(values[0]));
  for (let i = 1; i < values.length; i++) equityCtx.lineTo(toX(i), toY(values[i]));
  equityCtx.strokeStyle = gradColor;
  equityCtx.lineWidth = 1.5;
  equityCtx.stroke();

  // Baseline (initial capital)
  const baseY = toY(initial);
  equityCtx.beginPath();
  equityCtx.moveTo(0, baseY);
  equityCtx.lineTo(W, baseY);
  equityCtx.strokeStyle = "rgba(255,255,255,0.12)";
  equityCtx.lineWidth = 0.8;
  equityCtx.setLineDash([3, 3]);
  equityCtx.stroke();
  equityCtx.setLineDash([]);
}

// ── Price display ─────────────────────────────────────────────────────────
function updatePrices(prices) {
  const fmt = v => v >= 10000
    ? "$" + (v / 1000).toFixed(1) + "k"
    : "$" + v.toFixed(0);

  const btcEl = document.getElementById("btc-val");
  const ethEl = document.getElementById("eth-val");

  if (btcEl && prices["BTC/USDT"]) {
    const prev = state.prevPrices["BTC/USDT"] || prices["BTC/USDT"];
    btcEl.textContent = fmt(prices["BTC/USDT"]);
    btcEl.className = "pc-val" + (prices["BTC/USDT"] > prev ? " up" : prices["BTC/USDT"] < prev ? " down" : "");
  }
  if (ethEl && prices["ETH/USDT"]) {
    const prev = state.prevPrices["ETH/USDT"] || prices["ETH/USDT"];
    ethEl.textContent = fmt(prices["ETH/USDT"]);
    ethEl.className = "pc-val" + (prices["ETH/USDT"] > prev ? " up" : prices["ETH/USDT"] < prev ? " down" : "");
  }
  state.prevPrices = { ...prices };
  state.prices = prices;
}

// ── Formatters ────────────────────────────────────────────────────────────
const fmtEur = v => (v >= 0 ? "+" : "") + v.toFixed(2) + " \u20ac";
const fmtPct = v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
const fmtTime = iso => {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
const domainClass = d => d === "ENERGY_GEO" ? "energy" : "ai";
const dirClass = d => d === "LONG" ? "long" : d === "SHORT" ? "short" : "neutral";

// ── Leaflet icons ─────────────────────────────────────────────────────────
const makeIcon = cls => L.divIcon({ className: "", html: `<div class="${cls}"></div>`, iconSize: [14,14], iconAnchor: [7,7] });

// ── Map markers ───────────────────────────────────────────────────────────
const markerCache = {};

function addEventMarker(ev) {
  if (!state.layers.energyEvents && ev.domain === "ENERGY_GEO") return;
  if (!state.layers.aiEvents     && ev.domain === "AI_RELEASES") return;

  const cls   = ev.domain === "ENERGY_GEO" ? "marker-energy" : "marker-ai";
  const layer = ev.domain === "ENERGY_GEO" ? layerGroups.energyEvents : layerGroups.aiEvents;
  const lk    = ev.domain === "ENERGY_GEO" ? "energyEvents" : "aiEvents";

  const marker = L.marker([ev.lat, ev.lon], { icon: makeIcon(cls) });
  const dirLbl = ev.direction !== "NEUTRAL"
    ? `<span class="ev-direction ${dirClass(ev.direction)}">${ev.direction}</span>` : "";
  marker.bindPopup(`
    <div class="popup-headline">${ev.headline}</div>
    <div class="popup-meta">
      <span class="ev-domain ${domainClass(ev.domain)}">${ev.domain}</span>
      ${dirLbl}
      <span class="popup-conf">conf ${(ev.confidence * 100).toFixed(0)}%</span>
      <span>${fmtTime(ev.timestamp)}</span>
    </div>`);
  marker.addTo(layer);
  markerCache[ev.id] = { marker, lk };

  // Prune oldest beyond 30 per domain
  const same = Object.values(markerCache).filter(m => m.lk === lk);
  if (same.length > 30) {
    same[0].marker.remove();
  }
}

const positionMarkers = {};

function refreshPositionMarkers(positions) {
  Object.values(positionMarkers).forEach(m => m.remove());
  Object.keys(positionMarkers).forEach(k => delete positionMarkers[k]);
  if (!state.layers.openPositions) return;

  positions.forEach(pos => {
    const marker = L.marker([pos.lat, pos.lon], { icon: makeIcon("marker-position") });
    const pnlCls = pos.pnl_eur >= 0 ? "pnl-pos" : "pnl-neg";
    marker.bindPopup(`
      <div class="popup-headline">${pos.symbol} — ${pos.direction}</div>
      <div class="popup-meta">
        <span>Entry: ${pos.entry_price.toLocaleString()}</span>
        <span class="${pnlCls}">PnL: ${fmtEur(pos.pnl_eur)}</span>
        <span>Size: ${pos.size_eur.toFixed(2)} \u20ac</span>
      </div>`);
    marker.addTo(layerGroups.openPositions);
    positionMarkers[pos.id] = marker;
  });
}

// ── Top bar ───────────────────────────────────────────────────────────────
function updateTopBar(s) {
  if (!s) return;
  const el = id => document.getElementById(id);
  const pnl = s.total_pnl, pp = s.total_pnl_pct;
  el("tb-balance").textContent = s.balance.toFixed(2) + " \u20ac";
  el("tb-pnl").textContent     = fmtEur(pnl);
  el("tb-pnl").className       = "value " + (pnl >= 0 ? "pos" : "neg");
  el("tb-pnlpct").textContent  = fmtPct(pp);
  el("tb-pnlpct").className    = "value " + (pp >= 0 ? "pos" : "neg");
  el("tb-trades").textContent  = s.total_trades;
  el("tb-winrate").textContent = s.win_rate + "%";
  el("tb-drawdown").textContent = s.drawdown_pct.toFixed(1) + "%";
  el("tb-open").textContent    = s.open_positions;
  el("tb-pf").textContent      = s.profit_factor != null ? s.profit_factor.toFixed(2) : "—";
}

// ── Left panel ────────────────────────────────────────────────────────────
function updateLeftPanel(s) {
  if (!s) return;
  const el = id => document.getElementById(id);
  const pnl = s.total_pnl;
  el("lp-balance").textContent = s.balance.toFixed(2) + " \u20ac";
  el("lp-pnl").textContent     = fmtEur(pnl);
  el("lp-pnl").className       = "s-value " + (pnl >= 0 ? "pnl-pos" : "pnl-neg");
  el("lp-dd").textContent      = s.drawdown_pct.toFixed(1) + "%";
  el("lp-wr").textContent      = s.win_rate + "%";
  el("lp-pf").textContent      = s.profit_factor != null ? s.profit_factor.toFixed(2) : "—";
  el("lp-avg").textContent     = s.avg_trade_pnl != null ? fmtEur(s.avg_trade_pnl) : "—";
  el("lp-trades").textContent  = s.total_trades;
}

// ── Events list ───────────────────────────────────────────────────────────
function renderEvents(events) {
  const list = document.getElementById("events-list");
  if (!events.length) {
    list.innerHTML = '<div class="placeholder">Waiting for events\u2026</div>';
    return;
  }
  list.innerHTML = events.slice(0, 40).map(ev => {
    const dc  = domainClass(ev.domain);
    const dir = ev.direction !== "NEUTRAL"
      ? `<span class="ev-direction ${dirClass(ev.direction)}">${ev.direction}</span>` : "";
    return `<div class="event-item" onclick="panToEvent('${ev.id}')">
      <span class="ev-domain ${dc}">${ev.domain === "ENERGY_GEO" ? "GEO" : "AI"}</span>
      <div class="ev-headline">${ev.headline}</div>
      <div class="ev-meta">${dir}<span>${(ev.confidence*100).toFixed(0)}% conf</span><span>${fmtTime(ev.timestamp)}</span></div>
    </div>`;
  }).join("");
}

window.panToEvent = id => {
  const ev = state.events.find(e => e.id === id);
  if (ev) map.flyTo([ev.lat, ev.lon], 5, { duration: 1.2 });
};

// ── Trades table ──────────────────────────────────────────────────────────
function renderTrades(trades, positions) {
  document.getElementById("open-count-badge").textContent = positions.length + " OPEN";
  const all = [...positions.map(t => ({ ...t, status: "OPEN" })), ...trades.slice(0, 40)];
  const tbody = document.querySelector("#trades-table tbody");
  tbody.innerHTML = all.map(t => {
    const pc  = t.pnl_eur >= 0 ? "pnl-pos" : "pnl-neg";
    const stc = (t.status || "open").toLowerCase().replace("_", "_");
    return `<tr>
      <td>${fmtTime(t.opened_at)}</td>
      <td>${t.symbol}</td>
      <td class="${dirClass(t.direction)}" style="font-weight:700">${t.direction}</td>
      <td>${t.entry_price.toLocaleString()}</td>
      <td>${t.exit_price ? t.exit_price.toLocaleString() : "—"}</td>
      <td>${t.size_eur.toFixed(2)} \u20ac</td>
      <td class="${pc}">${fmtEur(t.pnl_eur)}</td>
      <td><span class="status-badge ${stc}">${t.status}</span></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)">${t.event_headline}</td>
    </tr>`;
  }).join("") || "<tr><td colspan='9' style='color:var(--text-muted);padding:10px'>No trades yet</td></tr>";
}

// ── Ticker ────────────────────────────────────────────────────────────────
function rebuildTicker(events) {
  const inner = document.getElementById("ticker-inner");
  const items = events.slice(0, 20).map(ev =>
    `<span>${ev.domain === "ENERGY_GEO" ? "\u26a1" : "\u{1F916}"} <span class="ticker-hl">${ev.headline}</span></span>`
  );
  inner.innerHTML = [...items, ...items].join("");
}

// ── Toast ─────────────────────────────────────────────────────────────────
function showToast(msg, cls) {
  const c = document.getElementById("toast-container");
  const d = document.createElement("div");
  d.className = "toast " + cls;
  d.innerHTML = msg;
  c.appendChild(d);
  setTimeout(() => d.remove(), 4000);
}

// ── Connection status ─────────────────────────────────────────────────────
function setConnected(yes) {
  state.connected = yes;
  document.getElementById("status-dot").className = "status-dot" + (yes ? "" : " offline");
  document.getElementById("status-label").textContent = yes ? "LIVE" : "RECONNECTING";
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWS() {
  const ws = new WebSocket(WS_URL);
  state.ws = ws;

  ws.onopen = () => {
    setConnected(true);
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      else clearInterval(ping);
    }, 20000);
  };

  ws.onmessage = e => {
    try { handleMessage(JSON.parse(e.data)); } catch (_) {}
  };

  ws.onclose = () => { setConnected(false); setTimeout(connectWS, 3000); };
  ws.onerror = () => ws.close();
}

function handleMessage(msg) {
  switch (msg.type) {

    case "snapshot": {
      const d = msg.data;
      state.summary   = d.summary;
      state.events    = d.events    || [];
      state.positions = d.positions || [];
      state.trades    = d.trades    || [];
      state.equityCurve = d.equity_curve || [];
      if (d.prices) updatePrices(d.prices);
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      renderEvents(state.events);
      renderTrades(state.trades, state.positions);
      refreshPositionMarkers(state.positions);
      state.events.forEach(addEventMarker);
      rebuildTicker(state.events);
      drawEquityChart(state.equityCurve);
      // Populate settings modal with server config
      if (d.summary && d.summary.config) populateSettings(d.summary.config);
      break;
    }

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
      const icon = t.direction === "LONG" ? "\u{1F4C8}" : "\u{1F4C9}";
      showToast(`${icon} OPEN ${t.direction} ${t.symbol}<br>${t.size_eur.toFixed(2)} \u20ac @ ${t.entry_price}`, "trade-open");
      break;
    }

    case "trade_close": {
      const t = msg.data;
      state.positions = state.positions.filter(p => p.id !== t.id);
      state.trades.unshift(t);
      state.trades = state.trades.slice(0, 500);
      refreshPositionMarkers(state.positions);
      renderTrades(state.trades, state.positions);
      const cls  = t.pnl_eur >= 0 ? "trade-close" : "trade-loss";
      const icon = t.status === "TP_HIT" ? "\u{1F3AF}" : t.status === "SL_HIT" ? "\u{1F6D1}" : "\u23F1";
      showToast(`${icon} ${t.status} ${t.direction} ${t.symbol}<br><strong>${fmtEur(t.pnl_eur)}</strong>`, cls);
      break;
    }

    case "positions_update":
      state.positions = msg.data;
      refreshPositionMarkers(state.positions);
      renderTrades(state.trades, state.positions);
      break;

    case "balance_update":
      state.summary = msg.data;
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      break;

    case "price_update":
      updatePrices(msg.data);
      break;

    case "config_update":
      populateSettings(msg.data);
      break;

    case "reset": {
      state.summary   = msg.data;
      state.events    = [];
      state.positions = [];
      state.trades    = [];
      state.equityCurve = [{ ts: new Date().toISOString(), balance: state.summary.balance }];
      Object.values(layerGroups).forEach(lg => lg.clearLayers());
      renderEvents([]);
      renderTrades([], []);
      updateTopBar(state.summary);
      updateLeftPanel(state.summary);
      drawEquityChart(state.equityCurve);
      showToast("\u{1F504} Reset \u2014 balance: " + state.summary.balance.toFixed(2) + " \u20ac", "trade-open");
      break;
    }
  }
}

// ── Layer toggles ─────────────────────────────────────────────────────────
function initLayerToggles() {
  const map_ = {
    "toggle-energy":    "energyEvents",
    "toggle-ai":        "aiEvents",
    "toggle-positions": "openPositions",
    "toggle-trades":    "tradeHistory",
  };
  Object.entries(map_).forEach(([id, key]) => {
    const cb = document.getElementById(id);
    if (!cb) return;
    cb.addEventListener("change", () => {
      state.layers[key] = cb.checked;
      if (cb.checked) layerGroups[key].addTo(map);
      else map.removeLayer(layerGroups[key]);
    });
  });
}

// ── Reset button ──────────────────────────────────────────────────────────
document.getElementById("reset-btn").addEventListener("click", async () => {
  const cap = parseFloat(document.getElementById("cfg-capital")?.value || "500");
  if (!confirm(`Reset bot to \u20ac${cap} starting balance?`)) return;
  await fetch(`${API_BASE}/reset?capital=${cap}`, { method: "POST" });
});

// ── Settings modal ────────────────────────────────────────────────────────
function populateSettings(cfg) {
  if (!cfg) return;
  const safe = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = val; };
  safe("cfg-capital", cfg.initial_capital);
  safe("cfg-tick",    cfg.tick_interval);
  safe("cfg-risk",    (cfg.risk_pct * 100).toFixed(1));
  safe("cfg-conf",    (cfg.min_confidence * 100).toFixed(0));
  safe("cfg-maxpos",  cfg.max_positions);
}

document.getElementById("settings-btn").addEventListener("click", () => {
  document.getElementById("settings-overlay").classList.remove("hidden");
});
document.getElementById("settings-close").addEventListener("click", () => {
  document.getElementById("settings-overlay").classList.add("hidden");
});
document.getElementById("cfg-cancel").addEventListener("click", () => {
  document.getElementById("settings-overlay").classList.add("hidden");
});
document.getElementById("settings-overlay").addEventListener("click", e => {
  if (e.target === e.currentTarget)
    document.getElementById("settings-overlay").classList.add("hidden");
});

document.getElementById("cfg-apply").addEventListener("click", async () => {
  const capital   = parseFloat(document.getElementById("cfg-capital").value);
  const tick      = parseFloat(document.getElementById("cfg-tick").value);
  const riskPct   = parseFloat(document.getElementById("cfg-risk").value) / 100;
  const minConf   = parseFloat(document.getElementById("cfg-conf").value)  / 100;
  const maxPos    = parseInt(document.getElementById("cfg-maxpos").value);

  // Apply config changes
  await fetch(`${API_BASE}/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tick_interval:  tick,
      risk_pct:       riskPct,
      min_confidence: minConf,
      max_positions:  maxPos,
    }),
  });

  // If capital changed, trigger a full reset
  if (state.summary && Math.abs(capital - state.summary.initial_capital) > 0.01) {
    await fetch(`${API_BASE}/reset?capital=${capital}`, { method: "POST" });
  }

  document.getElementById("settings-overlay").classList.add("hidden");
  showToast("\u2713 Settings applied", "trade-open");
});

// ── Clock ─────────────────────────────────────────────────────────────────
function updateClock() {
  document.getElementById("clock").textContent =
    new Date().toUTCString().replace(" GMT", " UTC");
}
setInterval(updateClock, 1000);
updateClock();

// ── Redraw chart on resize ────────────────────────────────────────────────
window.addEventListener("resize", () => {
  if (state.equityCurve.length) drawEquityChart(state.equityCurve);
});

// ── Init ──────────────────────────────────────────────────────────────────
initLayerToggles();
connectWS();
