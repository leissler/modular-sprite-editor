#!/bin/bash
# MacOS Build Script

# Check if venv exists and is valid for Mac (has bin/activate)
# Check if venv exists and is valid for Mac (has bin/activate)
if [ -d ".venv_mac" ] && [ ! -f ".venv_mac/bin/activate" ]; then
    echo "Detected invalid/incompatible .venv_mac. Removing..."
    rm -rf .venv_mac
fi

if [ ! -d ".venv_mac" ]; then
    echo "Creating virtual environment (.venv_mac)..."
    python3 -m venv .venv_mac
fi

source .venv_mac/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Clean previous builds
rm -rf build/mac dist/mac

echo "Running PyInstaller..."
python3 -m PyInstaller --clean --noconfirm --distpath dist/mac --workpath build/mac build_mac.spec

# Cleanup redundant directory (keep only the .app)
if [ -d "dist/mac/ModularSpriteEditor" ]; then
    echo "removing raw executable directory..."
    rm -rf dist/mac/ModularSpriteEditor
fi

echo "Build complete. App located at dist/mac/ModularSpriteEditor.app"
