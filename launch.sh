#!/usr/bin/env bash
# =============================================================================
# ndbot — Cross-platform launcher (Linux / macOS / WSL / Git Bash on Windows)
#
# Usage:
#   ./launch.sh                     # Interactive menu
#   ./launch.sh simulate            # Run simulation
#   ./launch.sh backtest            # Run backtest
#   ./launch.sh event-study         # Run event study
#   ./launch.sh walkforward         # Run walk-forward validation
#   ./launch.sh grid                # Run grid search
#   ./launch.sh monte-carlo         # Run Monte Carlo robustness test
#   ./launch.sh paper               # Run paper trading
#   ./launch.sh seed-demo           # Run seed demo
#   ./launch.sh status              # Show status
#   ./launch.sh health              # System health check
#   ./launch.sh dashboard           # Start web dashboard
#   ./launch.sh install             # Install dependencies
#   ./launch.sh test                # Run test suite
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="${NDBOT_CONFIG:-config/sample.yaml}"
LOG_LEVEL="${NDBOT_LOG_LEVEL:-INFO}"
SEED="${NDBOT_SEED:-42}"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

banner() {
    echo -e "${CYAN}${BOLD}"
    echo "  ███╗   ██╗██████╗ ██████╗  ██████╗ ████████╗"
    echo "  ████╗  ██║██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝"
    echo "  ██╔██╗ ██║██║  ██║██████╔╝██║   ██║   ██║   "
    echo "  ██║╚██╗██║██║  ██║██╔══██╗██║   ██║   ██║   "
    echo "  ██║ ╚████║██████╔╝██████╔╝╚██████╔╝   ██║   "
    echo "  ╚═╝  ╚═══╝╚═════╝ ╚═════╝  ╚═════╝    ╚═╝   "
    echo -e "${NC}"
    echo -e "  ${BOLD}News-Driven Trading Research Framework${NC}"
    echo ""
}

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON=python3
    elif command -v python &>/dev/null; then
        PYTHON=python
    else
        echo -e "${RED}Python not found. Install Python 3.10+ first.${NC}"
        exit 1
    fi

    # Verify version >= 3.10
    PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
        echo -e "${RED}Python >= 3.10 required (found $PY_VERSION)${NC}"
        exit 1
    fi
    echo -e "${GREEN}Using Python $PY_VERSION ($PYTHON)${NC}"
}

ensure_venv() {
    if [ ! -d ".venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        $PYTHON -m venv .venv
    fi

    # Activate venv
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f ".venv/Scripts/activate" ]; then
        source .venv/Scripts/activate
    fi
}

ensure_installed() {
    if ! $PYTHON -c "import ndbot" 2>/dev/null; then
        echo -e "${YELLOW}Installing ndbot...${NC}"
        pip install -e ".[dev]" --quiet
    fi
}

do_install() {
    check_python
    ensure_venv
    echo -e "${CYAN}Installing all dependencies...${NC}"
    pip install -e ".[dev]"
    echo -e "${GREEN}Installation complete.${NC}"
}

do_test() {
    check_python
    ensure_venv
    ensure_installed
    echo -e "${CYAN}Running test suite...${NC}"
    $PYTHON -m pytest tests/ -v --tb=short
}

do_command() {
    local cmd="$1"
    shift
    check_python
    ensure_venv
    ensure_installed

    case "$cmd" in
        simulate)
            $PYTHON -m ndbot.cli simulate -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        backtest)
            $PYTHON -m ndbot.cli backtest -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        event-study)
            $PYTHON -m ndbot.cli event-study -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        walkforward)
            $PYTHON -m ndbot.cli walkforward -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        grid)
            $PYTHON -m ndbot.cli grid -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        monte-carlo)
            $PYTHON -m ndbot.cli monte-carlo -c "$CONFIG" --seed "$SEED" --log-level "$LOG_LEVEL" "$@"
            ;;
        paper)
            $PYTHON -m ndbot.cli paper -c "$CONFIG" --log-level "$LOG_LEVEL" "$@"
            ;;
        seed-demo)
            $PYTHON -m ndbot.cli seed-demo --seed "$SEED" "$@"
            ;;
        status)
            $PYTHON -m ndbot.cli status "$@"
            ;;
        health)
            $PYTHON -m ndbot.cli health "$@"
            ;;
        dashboard)
            echo -e "${CYAN}Starting web dashboard on http://localhost:8000 ...${NC}"
            $PYTHON -m uvicorn ndbot.api.app:create_app --host 0.0.0.0 --port 8000 --factory "$@"
            ;;
        validate-config)
            $PYTHON -m ndbot.cli validate-config -c "$CONFIG" "$@"
            ;;
        export)
            $PYTHON -m ndbot.cli export "$@"
            ;;
        *)
            echo -e "${RED}Unknown command: $cmd${NC}"
            show_help
            exit 1
            ;;
    esac
}

show_help() {
    echo -e "${BOLD}Available commands:${NC}"
    echo "  simulate        Run event-driven simulation"
    echo "  backtest        Replay stored events + candles"
    echo "  event-study     Run event study analysis"
    echo "  walkforward     Walk-forward out-of-sample validation"
    echo "  grid            Parameter grid search"
    echo "  monte-carlo     Monte Carlo robustness testing"
    echo "  paper           Paper trading (sandbox/testnet)"
    echo "  seed-demo       Quick demo (no config needed)"
    echo "  status          Show recent runs"
    echo "  health          System health check"
    echo "  dashboard       Start web dashboard"
    echo "  validate-config Validate config file"
    echo "  export          Export data to CSV/JSON"
    echo "  install         Install dependencies"
    echo "  test            Run test suite"
    echo ""
    echo -e "${BOLD}Environment variables:${NC}"
    echo "  NDBOT_CONFIG     Config file path (default: config/sample.yaml)"
    echo "  NDBOT_LOG_LEVEL  Log level (default: INFO)"
    echo "  NDBOT_SEED       Random seed (default: 42)"
}

interactive_menu() {
    banner
    echo -e "${BOLD}Select a command:${NC}"
    echo ""
    echo "  1) simulate        6) monte-carlo"
    echo "  2) backtest        7) paper"
    echo "  3) event-study     8) seed-demo"
    echo "  4) walkforward     9) status"
    echo "  5) grid           10) health"
    echo ""
    echo "  i) install         t) test"
    echo "  d) dashboard       q) quit"
    echo ""
    read -rp "Choice: " choice

    case "$choice" in
        1) do_command simulate ;;
        2) do_command backtest ;;
        3) do_command event-study ;;
        4) do_command walkforward ;;
        5) do_command grid ;;
        6) do_command monte-carlo ;;
        7) do_command paper ;;
        8) do_command seed-demo ;;
        9) do_command status ;;
        10) do_command health ;;
        i|I) do_install ;;
        t|T) do_test ;;
        d|D) do_command dashboard ;;
        q|Q) echo "Bye." ; exit 0 ;;
        *) echo -e "${RED}Invalid choice${NC}" ; exit 1 ;;
    esac
}

# --- Main entry ---
if [ $# -eq 0 ]; then
    interactive_menu
elif [ "$1" = "install" ]; then
    do_install
elif [ "$1" = "test" ]; then
    do_test
elif [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    banner
    show_help
else
    do_command "$@"
fi
