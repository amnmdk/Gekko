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

REM --- Detect if launched by double-click (no parent console) ---
set "INTERACTIVE=0"
if "%~1"=="" set "INTERACTIVE=1"

REM --- Find Python ---
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if not defined PYTHON (
    where python3 >nul 2>&1 && set PYTHON=python3
)
if not defined PYTHON (
    echo [ERROR] Python not found. Install Python 3.10+ first.
    goto :pause_and_exit
)

REM --- Route command ---
if "%~1"=="" goto :menu
if /i "%~1"=="install" goto :install
if /i "%~1"=="test" goto :test
if /i "%~1"=="research-lab" goto :run_command
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
echo   11) research-lab
echo.
echo    I) install         T) test
echo    D) dashboard       Q) quit
echo.
set /p choice="Choice: "

if "%choice%"=="1" (set "CMD=simulate" & goto :run_command)
if "%choice%"=="2" (set "CMD=backtest" & goto :run_command)
if "%choice%"=="3" (set "CMD=event-study" & goto :run_command)
if "%choice%"=="4" (set "CMD=walkforward" & goto :run_command)
if "%choice%"=="5" (set "CMD=grid" & goto :run_command)
if "%choice%"=="6" (set "CMD=monte-carlo" & goto :run_command)
if "%choice%"=="7" (set "CMD=paper" & goto :run_command)
if "%choice%"=="8" (set "CMD=seed-demo" & goto :run_command)
if "%choice%"=="9" (set "CMD=status" & goto :run_command)
if "%choice%"=="10" (set "CMD=health" & goto :run_command)
if "%choice%"=="11" (set "CMD=research-lab" & goto :run_command)
if /i "%choice%"=="i" goto :install
if /i "%choice%"=="t" goto :test
if /i "%choice%"=="d" (set "CMD=dashboard" & goto :run_command)
if /i "%choice%"=="q" exit /b 0
echo [ERROR] Invalid choice
exit /b 1

:ensure_venv
if not exist ".venv" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :pause_and_exit
    )
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
    if errorlevel 1 (
        echo [ERROR] pip install failed. See errors above.
        goto :pause_and_exit
    )
)
goto :eof

:install
call :ensure_venv
echo Installing all dependencies...
pip install -e ".[dev]"
if errorlevel 1 (
    echo [ERROR] Installation failed. See errors above.
    goto :pause_and_exit
)
echo Installation complete.
goto :done

:test
call :ensure_venv
call :ensure_installed
echo Running test suite...
%PYTHON% -m pytest tests/ -v --tb=short
goto :done

:run_command
if not defined CMD set CMD=%~1
call :ensure_venv
call :ensure_installed

if /i "%CMD%"=="simulate" (
    ndbot simulate -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="backtest" (
    ndbot backtest -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="event-study" (
    ndbot event-study -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="walkforward" (
    ndbot walkforward -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="grid" (
    ndbot grid -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="monte-carlo" (
    ndbot monte-carlo -c "%NDBOT_CONFIG%" --seed %NDBOT_SEED% --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="paper" (
    ndbot paper -c "%NDBOT_CONFIG%" --log-level %NDBOT_LOG_LEVEL%
) else if /i "%CMD%"=="seed-demo" (
    ndbot seed-demo --seed %NDBOT_SEED%
) else if /i "%CMD%"=="status" (
    ndbot status
) else if /i "%CMD%"=="health" (
    ndbot health
) else if /i "%CMD%"=="research-lab" (
    ndbot research-lab
) else if /i "%CMD%"=="dashboard" (
    echo Starting web dashboard on http://localhost:8000 ...
    start http://localhost:8000
    %PYTHON% -m uvicorn ndbot.api.app:app --host 0.0.0.0 --port 8000
) else if /i "%CMD%"=="validate-config" (
    ndbot validate-config -c "%NDBOT_CONFIG%"
) else if /i "%CMD%"=="export" (
    ndbot export %2 %3 %4 %5
) else (
    echo [ERROR] Unknown command: %CMD%
    goto :help
)
if errorlevel 1 goto :pause_and_exit
goto :done

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
echo   research-lab    Full quant research lab demo
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
goto :done

:pause_and_exit
echo.
pause
exit /b 1

:done
echo.
pause
