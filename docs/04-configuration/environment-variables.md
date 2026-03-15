# Environment Variables

Environment variables override config file values. Use them for secrets and deployment-specific settings.

---

## Pattern

```
NDBOT__<SECTION>__<KEY>=value
```

Double underscore (`__`) separates section and key.

---

## Available Overrides

### Paper Trading Credentials

```bash
export NDBOT__PAPER__API_KEY=your_testnet_api_key
export NDBOT__PAPER__API_SECRET=your_testnet_api_secret
export NDBOT__PAPER__DRY_RUN=true
export NDBOT__PAPER__EXCHANGE_ID=binance
```

**Never** put API keys in config files or commit them to git.

### Logging

```bash
export NDBOT__LOG_LEVEL=DEBUG
```

---

## Docker Environment

In `docker-compose.yml`:

```yaml
services:
  backend:
    environment:
      - NDBOT__PAPER__API_KEY=${PAPER_API_KEY}
      - NDBOT__PAPER__API_SECRET=${PAPER_API_SECRET}
      - NDBOT__LOG_LEVEL=INFO
```

Or use a `.env` file (gitignored):

```bash
# .env
PAPER_API_KEY=your_testnet_key
PAPER_API_SECRET=your_testnet_secret
```

---

## Systemd Service

```ini
[Service]
Environment=NDBOT__PAPER__DRY_RUN=true
Environment=NDBOT__PAPER__API_KEY=your_key
Environment=NDBOT__PAPER__API_SECRET=your_secret
```

Or use `EnvironmentFile`:

```ini
[Service]
EnvironmentFile=/home/pi/.ndbot-env
```

---

## Security Best Practices

1. **Never commit secrets** — Use `.env` files (gitignored) or env vars
2. **Use testnet keys** — Never real exchange credentials
3. **Rotate keys** — Change API keys periodically
4. **Principle of least privilege** — Testnet keys should have read + trade permissions only, no withdrawal
