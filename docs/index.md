# ndbot Documentation

> News-Driven Intraday Trading Research Framework — v0.2.0 (Beta)

Welcome to the ndbot documentation. This knowledge base is organised for optimal reading in **Notion** or **Obsidian** — each section is a folder with focused, self-contained files.

---

## Navigation

### 📦 Getting Started
- [[01-getting-started/overview|Overview]] — What ndbot is (and isn't)
- [[01-getting-started/installation|Installation]] — Native, Docker, Raspberry Pi
- [[01-getting-started/quickstart|Quickstart]] — First run in under 5 minutes
- [[01-getting-started/cli-reference|CLI Reference]] — All 10 commands explained

### 🏗️ Architecture
- [[02-architecture/system-design|System Design]] — Module map and signal flow
- [[02-architecture/data-flow|Data Flow]] — From RSS feed to trade execution
- [[02-architecture/directory-structure|Directory Structure]] — File-by-file breakdown

### 📚 Modules
- [[03-modules/feeds|Feeds]] — RSS reader, synthetic generator, feed manager
- [[03-modules/classifier|Classifier]] — Keyword classification and entity extraction
- [[03-modules/signals|Signals]] — Confidence model, signal generators, confirmation
- [[03-modules/market|Market Data]] — OHLCV feeds, regime detection, synthetic candles
- [[03-modules/portfolio|Portfolio]] — Position lifecycle, risk engine, metrics
- [[03-modules/execution|Execution]] — Simulation engine, paper trading engine
- [[03-modules/storage|Storage]] — SQLAlchemy ORM, database abstraction

### ⚙️ Configuration
- [[04-configuration/config-reference|Config Reference]] — Every field explained
- [[04-configuration/config-examples|Config Examples]] — Common setups
- [[04-configuration/environment-variables|Environment Variables]] — Overrides and secrets

### 🔬 Research & Analytics
- [[05-research/event-study|Event Study]] — Methodology, interpretation, limitations
- [[05-research/walkforward|Walk-Forward Validation]] — OOS testing methodology
- [[05-research/grid-search|Grid Search]] — Parameter optimisation
- [[05-research/interpreting-results|Interpreting Results]] — What the numbers mean

### 🚀 Operations
- [[06-operations/deployment|Deployment]] — Native, Docker, systemd
- [[06-operations/docker|Docker Guide]] — Compose, ARM64, multi-stage
- [[06-operations/ci-cd|CI/CD Pipeline]] — GitHub Actions workflow
- [[06-operations/monitoring|Monitoring & Logging]] — Logs, health checks

### 🌐 API & Dashboard
- [[07-api-dashboard/rest-api|REST API]] — All endpoints documented
- [[07-api-dashboard/websocket|WebSocket]] — Real-time data stream
- [[07-api-dashboard/dashboard|Dashboard]] — Frontend UI guide

### 🛡️ Risk & Safety
- [[08-risk-safety/risk-management|Risk Management]] — How the risk engine works
- [[08-risk-safety/safety-guards|Safety Guards]] — Circuit breakers and limits
- [[08-risk-safety/paper-trading|Paper Trading Safety]] — Sandbox-first approach

### 🧪 Development
- [[09-development/contributing|Contributing]] — Dev setup, code style, testing
- [[09-development/test-suite|Test Suite]] — 87 tests documented
- [[09-development/changelog|Changelog]] — Version history

### ❓ Troubleshooting
- [[10-troubleshooting/faq|FAQ]] — Common questions answered
- [[10-troubleshooting/common-errors|Common Errors]] — Error messages and fixes
- [[10-troubleshooting/performance|Performance]] — Tuning for Pi 5

---

## Quick Links

| Action | Command |
|---|---|
| Run demo (no config needed) | `ndbot seed-demo` |
| Simulate with config | `ndbot simulate -c config/sample.yaml` |
| Validate config | `ndbot validate-config -c config/sample.yaml` |
| Check recent runs | `ndbot status` |
| Export trades | `ndbot export --run-id <id>` |
| Run tests | `pytest tests/ -v` |

---

*Last updated: 2026-03-14 — ndbot v0.2.0*
