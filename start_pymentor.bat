@echo off
setlocal enabledelayedexpansion
title PyMentor - AI Student Practice Platform

:: Set working directory to the pymentor folder
cd /d "%~dp0"

echo ============================================================
echo        PyMentor - Automated Startup and Environment Check
echo ============================================================
echo.

:: 1. Detect working Python command
set "PY_CMD="

:: Check if 'py' launcher works
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 -c "import sys" >nul 2>nul
    if !errorlevel! equ 0 (
        set "PY_CMD=py -3"
    )
)

:: Check if 'python' command works
if "!PY_CMD!"=="" (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        python -c "import sys" >nul 2>nul
        if !errorlevel! equ 0 (
            set "PY_CMD=python"
        )
    )
)

:: Check if 'python3' command works
if "!PY_CMD!"=="" (
    where python3 >nul 2>nul
    if %errorlevel% equ 0 (
        python3 -c "import sys" >nul 2>nul
        if !errorlevel! equ 0 (
            set "PY_CMD=python3"
        )
    )
)

:: If no Python is found, show clear instructions
if "!PY_CMD!"=="" (
    echo [ERROR] Python 3 was not detected on this computer!
    echo.
    echo Please install Python 3.10 or higher from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: When installing, make sure to check the box:
    echo   "[X] Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo [OK] Detected Python: !PY_CMD!
!PY_CMD! --version
echo.

:: 2. Check if required dependencies are installed
echo [*] Checking required dependencies...
!PY_CMD! -c "import fastapi, uvicorn, google.genai, pydantic, dotenv, passlib" >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Missing dependencies detected.
    echo [*] Installing required packages using pip...
    echo [*] Command: !PY_CMD! -m pip install -r "%~dp0requirements.txt"
    echo.
    !PY_CMD! -m pip install -r "%~dp0requirements.txt"
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Failed to install dependencies.
        echo Please ensure you are connected to the internet and run:
        echo   !PY_CMD! -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Dependencies installed successfully!
) else (
    echo [OK] All dependencies are already installed.
)
echo.

:: 3. Launch PyMentor
echo [*] Launching PyMentor server...
echo.
!PY_CMD! "%~dp0run.py"

if %errorlevel% neq 0 (
    echo.
    echo [WARNING] Server stopped with error code %errorlevel%.
    pause
)
