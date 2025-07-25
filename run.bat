@echo off
REM SKCC Skimmer Runtime Script for Windows using uv
REM Uses uv for fast dependency management and virtual environment handling

REM Enable delayed variable expansion for use in for loops
setlocal enabledelayedexpansion

REM Prevent Python from creating __pycache__ directories
set PYTHONDONTWRITEBYTECODE=1

REM Check if uv is installed
uv --version >nul 2>&1
if errorlevel 1 (
    echo Error: uv is not installed or not in PATH
    echo Please install uv first:
    echo   1. Download from: https://github.com/astral-sh/uv
    echo   2. Or install via pip: pip install uv
    echo   3. Or install via pipx: pipx install uv
    pause
    exit /b 1
)

REM Set Windows-specific virtual environment
set UV_PROJECT_ENVIRONMENT=.venv-windows

REM Create/sync virtual environment - let uv handle Python version requirements
uv sync --quiet
if errorlevel 1 (
    echo First sync attempt failed, trying to install Python 3.11 via uv...
    uv python install 3.11 --quiet
    if errorlevel 1 (
        echo Failed to install Python 3.11 via uv
        echo Please install Python 3.11+ manually from: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    
    echo Python 3.11 installed, retrying environment sync...
    uv sync --quiet
    if errorlevel 1 (
        echo Environment sync still failed, cleaning old virtual environment...
        if exist .venv (
            rmdir /s /q .venv 2>nul
            REM Handle stubborn symlinks on Windows
            if exist .venv\lib64 (
                del /f /q .venv\lib64 2>nul
                rmdir /s /q .venv 2>nul
            )
        )
        
        echo Final attempt with fresh virtual environment...
        uv sync --quiet
        if errorlevel 1 (
            echo Error: Failed to create virtual environment
            echo Make sure pyproject.toml exists and is valid
            pause
            exit /b 1
        )
    )
)

:version_stamp

REM Generate version stamp if .git exists and cVersion.py doesn't exist
if exist .git if not exist cVersion.py (
    REM Clear variables first
    set VERSION=
    set GIT_SHA=
    set HAS_CHANGES=
    set COMMIT_DATE=
    set SHORT_SHA=
    set VERSION_STAMP=

    REM Try to get tag first
    for /f "tokens=*" %%i in ('git describe --tags --exact-match HEAD 2^>nul') do set VERSION=%%i
    if defined VERSION (
        for /f "tokens=*" %%i in ('git rev-list -n 1 "%VERSION%" 2^>nul') do set GIT_SHA=%%i
    ) else (
        REM No tag, use current commit
        for /f "tokens=*" %%i in ('git rev-parse HEAD 2^>nul') do set GIT_SHA=%%i
        for /f "tokens=*" %%i in ('git rev-parse --short HEAD 2^>nul') do set VERSION=%%i
    )

    REM Only proceed if we got valid git data
    if defined GIT_SHA if defined VERSION (
        REM Check for modified files
        for /f "tokens=*" %%i in ('git status --porcelain 2^>nul') do set HAS_CHANGES=%%i
        if defined HAS_CHANGES set VERSION=!VERSION!-

        REM Get commit date and short SHA
        for /f "tokens=*" %%i in ('git log -1 --format=%%ad --date=short "!GIT_SHA!" 2^>nul') do set COMMIT_DATE=%%i
        for /f "tokens=*" %%i in ('git rev-parse --short "!GIT_SHA!" 2^>nul') do set SHORT_SHA=%%i

        REM Create version stamp with available data
        if defined SHORT_SHA (
            REM Create version stamp - use current date if commit date unavailable
            if not defined COMMIT_DATE (
                for /f "tokens=2-4 delims=/ " %%a in ('date /t') do set COMMIT_DATE=%%c-%%a-%%b
            )
            
            if "!VERSION!"=="!SHORT_SHA!" (
                set "VERSION_STAMP=!VERSION! / !COMMIT_DATE!"
            ) else (
                set "VERSION_STAMP=!VERSION! / !COMMIT_DATE! - !SHORT_SHA!"
            )

            REM Write cVersion.py
            > cVersion.py echo VERSION = '!VERSION_STAMP!'
        )
    )
)

REM Run the application with all command line arguments using uv
uv run skcc_skimmer.py %*
