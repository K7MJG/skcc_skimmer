@echo off
setlocal

REM Check if venv already exists
if exist .venv\Scripts\activate.bat (
    echo Virtual environment already exists. Skipping creation.
) else (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
)

REM Activate virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    exit /b 1
)

REM Upgrade pip (optional)
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install all requirements
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    exit /b 1
)

echo Virtual environment setup complete.
endlocal
