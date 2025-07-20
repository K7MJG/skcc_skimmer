@echo off
REM SKCC Skimmer Runtime Script for Windows
REM Creates virtual environment if needed and runs the application

REM Prevent Python from creating __pycache__ directories
set PYTHONDONTWRITEBYTECODE=1

REM Check if virtual environment exists, create if not
if not exist .venv (
    REM Check Python version before creating venv
    python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Error: Python 3.11 or higher is required
        for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo Current Python version: %%i
        echo Please install Python 3.11+ and try again
        pause
        exit /b 1
    )
    
    echo Creating Python virtual environment...
    python -m venv .venv >nul 2>&1
    if errorlevel 1 (
        echo Error: Failed to create virtual environment
        echo Make sure Python 3.11+ is installed and working correctly
        pause
        exit /b 1
    )
    
    echo Installing required packages...
    .venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
    .venv\Scripts\python.exe -m pip install -r requirements.txt >nul 2>&1
    if errorlevel 1 (
        echo Error: Failed to install requirements
        pause
        exit /b 1
    )
)

REM Generate version stamp if .git exists
if exist .git (
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
    
    REM Ensure we have required variables - exit silently if Git commands fail
    if defined GIT_SHA if defined VERSION (
        REM Check for modified files
        for /f "tokens=*" %%i in ('git status --porcelain 2^>nul') do set HAS_CHANGES=%%i
        if defined HAS_CHANGES set VERSION=%VERSION%-
        
        REM Get commit date and short SHA
        for /f "tokens=*" %%i in ('git show -s --format^=%%as "%GIT_SHA%" 2^>nul') do set COMMIT_DATE=%%i
        for /f "tokens=*" %%i in ('git rev-parse --short "%GIT_SHA%" 2^>nul') do set SHORT_SHA=%%i
        
        REM Create version stamp
        if "%VERSION%"=="%SHORT_SHA%" (
            set VERSION_STAMP=%VERSION% / %COMMIT_DATE%
        ) else (
            set VERSION_STAMP=%VERSION% / %COMMIT_DATE% ^(%SHORT_SHA%^)
        )
        
        REM Write cVersion.py
        echo VERSION = '%VERSION_STAMP%' > cVersion.py
    )
)

REM Run the application with all command line arguments
.venv\Scripts\python.exe skcc_skimmer.py %*