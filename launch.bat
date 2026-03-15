@echo off
REM =============================================================================
REM ndbot — Cross-platform launcher (Windows CMD / PowerShell)
REM
REM Usage:
REM   launch.bat                     Interactive menu
REM   launch.bat simulate            Run simulation
REM   launch.bat backtest            Run backtest
REM   launch.bat event-study         Run event study
REM   launch.bat walkforward         Walk-forward validation
REM   launch.bat grid                Grid search
REM   launch.bat monte-carlo         Monte Carlo robustness test
REM   launch.bat paper               Paper trading
REM   launch.bat seed-demo           Seed demo
REM   launch.bat status              Show status
REM   launch.bat health              System health check
REM   launch.bat dashboard           Start web dashboard
REM   launch.bat install             Install dependencies
REM   launch.bat test                Run test suite
REM =============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not defined NDBOT_CONFIG set NDBOT_CONFIG=config\sample.yaml
if not defined NDBOT_LOG_LEVEL set NDBOT_LOG_LEVEL=INFO
if not defined NDBOT_SEED set NDBOT_SEED=42

REM --- Find Python ---
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    where python3 >nul 2>&1 && set PYTHON=python3
)
if not defined PYTHON (
    echo [ERROR] Python not found. Install Python 3.10+ first.
    exit /b 1
)

REM --- Route command ---
if "%~1"=="" goto :menu
if /i "%~1"=="install" goto :install
if /i "%~1"=="test" goto :test
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
goto :run_command

:menu
echo.
echo   ███╗   ██╗██████╗ ██████╗  ██████╗ ████████╗
echo   ████╗  ██║██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝
echo   ██╔██╗ ██║██║  ██║██████╔╝██║   ██║   ██║
echo   ██║╚██╗██║██║  ██║██╔══██╗██║   ██║   ██║
echo   ██║ ╚████║██████╔╝██████╔╝╚██████╔╝   ██║
echo   ╚═╝  ╚═══╝╚═════╝ ╚═════╝  ╚═════╝    ╚═╝
echo.
echo   News-Driven Trading Research Framework
echo.
echo   Select a command:
echo.
echo    1) simulate        6) monte-carlo
echo    2) backtest        7) paper
echo    3) event-study     8) seed-demo
echo    4) walkforward     9) status
echo    5) grid           10) health
echo.
echo    I) install         T) test
echo    D) dashboard       Q) quit
echo.
set /p choice="Choice: "

if "%choice%"=="1" (set CMD=simulate & goto :run_command)
if "%choice%"=="2" (set CMD=backtest & goto :run_command)
if "%choice%"=="3" (set CMD=event-study & goto :run_command)
if "%choice%"=="4" (set CMD=walkforward & goto :run_command)
if "%choice%"=="5" (set CMD=grid & goto :run_command)
if "%choice%"=="6" (set CMD=monte-carlo & goto :run_command)
if "%choice%"=="7" (set CMD=paper & goto :run_command)
if "%choice%"=="8" (set CMD=seed-demo & goto :run_command)
if "%choice%"=="9" (set CMD=status & goto :run_command)
if "%choice%"=="10" (set CMD=health & goto :run_command)
if /i "%choice%"=="i" goto :install
if /i "%choice%"=="t" goto :test
if /i "%choice%"=="d" (set CMD=dashboard & goto :run_command)
if /i "%choice%"=="q" exit /b 0
echo [ERROR] Invalid choice
exit /b 1

:ensure_venv
if not exist ".venv" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)
goto :eof

:ensure_installed
%PYTHON% -c "import ndbot" >nul 2>&1
if errorlevel 1 (
    echo Installing ndbot...
    pip install -e ".[dev]" --quiet
)
goto :eof

:install
call :ensure_venv
echo Installing all dependencies...
pip install -e ".[dev]"
echo Installation complete.
goto :eof

:test
call :ensure_venv
call :ensure_installed
echo Running test suite...
%PYTHON% -m pytest tests/ -v --tb=short
goto :eof

:run_command
if not defined CMD set CMD=%~1
call :ensure_venv
call :ensure_installed

if /i "%CMD%"=="simulate" (
    %PYTHON% -m ndbot.cli simulate -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="backtest" (
    %PYTHON% -m ndbot.cli backtest -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="event-study" (
    %PYTHON% -m ndbot.cli event-study -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="walkforward" (
    %PYTHON% -m ndbot.cli walkforward -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="grid" (
    %PYTHON% -m ndbot.cli grid -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="monte-carlo" (
    %PYTHON% -m ndbot.cli monte-carlo -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="paper" (
    %PYTHON% -m ndbot.cli paper -c "%NDBOT_CONFIG%" --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="seed-demo" (
    %PYTHON% -m ndbot.cli seed-demo --seed %NDBOT_SEED%
) else if /i "%CMD%"=="status" (
    %PYTHON% -m ndbot.cli status
) else if /i "%CMD%"=="health" (
    %PYTHON% -m ndbot.cli health
) else if /i "%CMD%"=="dashboard" (
    echo Starting web dashboard on http://localhost:8000 ...
    %PYTHON% -m uvicorn ndbot.api.app:create_app --host 0.0.0.0 --port 8000 --factory
) else if /i "%CMD%"=="validate-config" (
    %PYTHON% -m ndbot.cli validate-config -c "%NDBOT_CONFIG%"
) else if /i "%CMD%"=="export" (
    %PYTHON% -m ndbot.cli export %2 %3 %4 %5
) else (
    echo [ERROR] Unknown command: %CMD%
    goto :help
)
goto :eof

:help
echo.
echo Available commands:
echo   simulate        Run event-driven simulation
echo   backtest        Replay stored events + candles
echo   event-study     Run event study analysis
echo   walkforward     Walk-forward out-of-sample validation
echo   grid            Parameter grid search
echo   monte-carlo     Monte Carlo robustness testing
echo   paper           Paper trading (sandbox/testnet)
echo   seed-demo       Quick demo (no config needed)
echo   status          Show recent runs
echo   health          System health check
echo   dashboard       Start web dashboard
echo   validate-config Validate config file
echo   export          Export data to CSV/JSON
echo   install         Install dependencies
echo   test            Run test suite
echo.
echo Environment variables:
echo   NDBOT_CONFIG     Config file path (default: config\sample.yaml)
echo   NDBOT_LOG_LEVEL  Log level (default: INFO)
echo   NDBOT_SEED       Random seed (default: 42)
goto :eof
