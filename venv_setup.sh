#!/bin/bash

set -e  # Exit immediately if a command fails

echo "Checking for virtual environment..."

if [ -d ".venv" ]; then
    echo "Virtual environment already exists. Skipping creation."
else
    echo "Creating virtual environment..."
    python3 -m venv .venv || {
        echo "Failed to create virtual environment."
        exit 1
    }
fi

echo "Activating virtual environment..."
# shellcheck source=/dev/null
source .venv/bin/activate || {
    echo "Failed to activate virtual environment."
    exit 1
}

echo "Upgrading pip..."
python -m pip install --upgrade pip

echo "Installing dependencies..."
pip install -r requirements.txt || {
    echo "Failed to install dependencies."
    exit 1
}

echo "Virtual environment setup complete."
