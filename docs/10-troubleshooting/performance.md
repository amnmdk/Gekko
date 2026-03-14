# Performance Tuning

## Raspberry Pi 5 Optimisation

### CPU

- ndbot is single-threaded for simulation (no GIL issues)
- Paper mode uses async I/O for feed polling (efficient)
- No heavy computation — keyword matching is O(n) per event
- Regime detection (pandas rolling) is the heaviest operation

### Memory

| Component | Memory Usage |
|---|---|
| Python interpreter | ~30 MB |
| Loaded candles (500) | ~5 MB |
| Loaded candles (50k) | ~500 MB |
| SQLite connection | ~10 MB |
| Feed manager | ~20 MB |
| Total (simulate) | ~200–500 MB |
| Total (paper) | ~500 MB–1 GB |

### Recommendations

1. **Limit candle history**: Set `candle_window: 200` (not 5000)
2. **Cap walk-forward candles**: `--n-events 100` with 50k candle max
3. **Use WARNING log level**: `--log-level WARNING` reduces I/O
4. **Avoid concurrent runs**: One ndbot process at a time on Pi
5. **Use swap file**: If RAM is limited, add a 2GB swap file

### Swap File Setup

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
```

---

## Database Performance

### SQLite Optimisation

ndbot uses SQLAlchemy with SQLite. For large databases (>100MB):

```bash
# Compact database
sqlite3 data/ndbot.db "VACUUM;"

# Check database size
ls -lh data/ndbot.db
```

### Retention

Old events can be purged:

```bash
sqlite3 data/ndbot.db "DELETE FROM events WHERE ingested_at < datetime('now', '-30 days');"
sqlite3 data/ndbot.db "VACUUM;"
```

---

## Network Performance (Paper Mode)

### Feed Polling

- Each RSS poll creates a new HTTP session (aiohttp)
- Timeout: 15 seconds per request
- Retry: 3 attempts with exponential backoff

### CCXT Exchange

- Candle fetches: ~200ms per request
- Price fetches: ~100ms per request
- Rate limits vary by exchange

### Reducing Network Load

1. Increase `poll_interval_seconds` (60→120→300)
2. Disable unused feeds (`enabled: false`)
3. Reduce `candle_window` (fewer historical candles fetched)

---

## Benchmark Reference

Measured on Raspberry Pi 5 (8GB, no overclock, NVMe SSD):

| Operation | Events | Candles | Time |
|---|---|---|---|
| `seed-demo` | 60 | 600 | 3.2s |
| `simulate` | 80 | 500 | 3.8s |
| `simulate` | 200 | 2000 | 8.5s |
| `backtest` (synthetic) | 80 | 500 | 3.5s |
| `event-study` | 60 | 2000 | 4.2s |
| `walkforward` | 400 | 50000 | 95s |
| `grid` (25 combos) | 200 | 1000 | 12s |
| `pytest tests/ -v` | — | — | 3.9s |

---

## Docker Performance

### Image Sizes

| Image | Size (ARM64) |
|---|---|
| ndbot CLI | ~450 MB |
| ndbot backend | ~480 MB |
| ndbot frontend | ~25 MB |

### Build Time (Pi 5 native)

| Image | Time |
|---|---|
| CLI | ~3 min |
| Backend | ~3 min |
| Frontend | ~10 sec |

### Tips

- Use Docker layer caching: requirements.txt layer rarely changes
- Mount volumes for data persistence (avoid rebuilding for data changes)
- Set memory limits in docker-compose to prevent OOM on Pi
