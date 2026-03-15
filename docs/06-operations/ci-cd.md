# CI/CD Pipeline

## GitHub Actions Workflow

The CI pipeline runs on every push and pull request. Located at `.github/workflows/ci.yml`.

---

## Pipeline Stages

### Job 1: Lint, Type-check, Test, Simulate

Runs on `ubuntu-latest` with Python 3.11.

```
Step 1: Checkout code
Step 2: Setup Python 3.11
Step 3: Install dependencies (requirements.txt + dev extras)
Step 4: Lint (ruff check src/ tests/)
Step 5: Format check (black --check)
Step 6: Syntax check (ast.parse all .py files)
Step 7: Mypy type check (non-blocking — allowed to fail)
Step 8: Pytest with coverage
Step 9: Upload coverage artifact
Step 10: CLI smoke tests
Step 11: Verify results
```

### CLI Smoke Tests

```bash
# Generate demo data
ndbot seed-demo --output-dir /tmp/demo-output

# Run simulation
ndbot simulate --config config/sample.yaml --seed 42
```

### Coverage

Tests run with:
```bash
pytest tests/ -v --cov=src/ndbot --cov-report=term-missing --cov-report=xml:coverage.xml
```

Coverage report is uploaded as a GitHub Actions artifact.

---

### Job 2: Docker Build

Depends on Job 1 passing.

```
Step 1: Setup QEMU (ARM64 emulation)
Step 2: Setup Docker Buildx
Step 3: Validate docker compose config
Step 4: Build Dockerfile.backend (linux/arm64)
Step 5: Build Dockerfile.frontend (linux/arm64)
```

Docker images are built but **not pushed** — this validates the Dockerfiles work on ARM64.

---

## Running CI Locally

You can replicate the CI pipeline locally:

```bash
# Lint
ruff check src/ tests/

# Format check
black --check src/ tests/

# Type check
mypy src/ndbot/

# Tests with coverage
pytest tests/ -v --cov=src/ndbot --cov-report=term-missing

# CLI smoke
ndbot seed-demo --output-dir /tmp/demo-output
ndbot simulate --config config/sample.yaml --seed 42

# Docker
docker compose config --quiet
docker buildx build --platform linux/arm64 -f Dockerfile.backend .
docker buildx build --platform linux/arm64 -f Dockerfile.frontend .
```

---

## Adding New Tests

When adding new test files:

1. Create `tests/test_<module>.py`
2. Follow existing patterns (fixtures, imports)
3. Run `ruff check tests/` to verify lint
4. Tests are auto-discovered by pytest via `pyproject.toml` config
5. Push — CI will run automatically

---

## Troubleshooting CI

| Issue | Fix |
|---|---|
| ruff fails | Run `ruff check --fix src/ tests/` locally |
| black fails | Run `black src/ tests/` locally |
| mypy fails | Non-blocking — check warnings but CI continues |
| pytest fails | Run `pytest tests/ -v --tb=long` for details |
| Docker build fails | Check Dockerfile syntax; verify base images exist |
