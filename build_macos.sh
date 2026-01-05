#!/bin/bash
# MacOS Build Script

# Check if venv exists and is valid for Mac (has bin/activate)
if [ -d ".venv" ] && [ ! -f ".venv/bin/activate" ]; then
    echo "Detected invalid/incompatible .venv (likely from Windows). Removing..."
    rm -rf .venv
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Clean previous builds
rm -rf build dist

echo "Running PyInstaller..."
python3 -m PyInstaller --clean --noconfirm build_mac.spec

echo "Build complete. App located at dist/ModularSpriteEditor.app"
