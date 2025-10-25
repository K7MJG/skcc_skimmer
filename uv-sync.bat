@echo off
REM Create/update .venv without using pyproject.toml
REM This script manually installs dependencies needed by skcc_skimmer.py

echo Creating/updating .venv with Python 3.14...
uv venv .venv --python 3.14

echo Installing dependencies...
uv pip install --python .venv\Scripts\python aiohttp aiofiles

echo Done! Virtual environment ready at .venv
