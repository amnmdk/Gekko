# Contributing

## Development Setup

```bash
# Clone
git clone https://github.com/amnmdk/Gekko.git
cd Gekko

# Create venv
python3.11 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

---

## Code Style

### Formatting

- **black** — Line length 100
- Run: `black src/ tests/`

### Linting

- **ruff** — Rules: E, F, I, N, W
- Run: `ruff check src/ tests/`
- Auto-fix: `ruff check --fix src/ tests/`

### Type Checking

- **mypy** — Strict mode disabled (gradual typing)
- Run: `mypy src/ndbot/`

### Import Ordering

ruff enforces I001 (isort-compatible). Imports must be sorted:
1. Standard library
2. Third-party packages
3. Local imports

---

## Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ -v --cov=src/ndbot --cov-report=term-missing
```

### Run a Specific Test

```bash
pytest tests/test_signals.py::test_energy_geo_bearish_yields_short -v
```

### Test Patterns

All tests follow these patterns:

1. **No external dependencies** — Tests use synthetic data only
2. **No network calls** — All feeds are mocked or synthetic
3. **Deterministic** — Fixed seeds produce identical results
4. **Clean state** — Each test gets fresh objects (no shared state)
5. **Fast** — Full suite runs in <5 seconds

---

## Adding a New Module

1. Create `src/ndbot/<module>/`
2. Add `__init__.py`
3. Implement the module
4. Add tests in `tests/test_<module>.py`
5. Run `ruff check` and `black`
6. Run `pytest tests/ -v`
7. Update `docs/03-modules/<module>.md`

---

## Adding a New CLI Command

1. Add the command function in `cli.py`
2. Decorate with `@main.command()`
3. Add Click options with help text
4. Add to the CLI Reference documentation
5. Add a smoke test in the CI workflow if appropriate

---

## Adding a New Test

1. Create test function in the appropriate test file
2. Use descriptive names: `test_<what>_<condition>_<expected>`
3. Use synthetic data (no external APIs)
4. Assert specific values where possible
5. Run `ruff check tests/` to verify lint

---

## Git Workflow

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make changes
3. Run tests: `pytest tests/ -v`
4. Run lint: `ruff check src/ tests/`
5. Commit with descriptive message
6. Push and create PR against `main`

---

## Project Conventions

| Convention | Standard |
|---|---|
| Python version | 3.11+ |
| Line length | 100 characters |
| Docstrings | Google-style |
| Type annotations | All public functions |
| Config validation | Pydantic v2 with Field constraints |
| Logging | `logging.getLogger(__name__)` |
| Error handling | Log + return None (no silent failures) |
| Imports | Absolute from package root |
