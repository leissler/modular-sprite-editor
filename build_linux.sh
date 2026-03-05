#!/bin/bash
# Linux Build Script

set -euo pipefail

if [ -d ".venv_linux" ] && [ ! -f ".venv_linux/bin/activate" ]; then
    echo "Detected invalid/incompatible .venv_linux. Removing..."
    rm -rf .venv_linux
fi

if [ ! -d ".venv_linux" ]; then
    echo "Creating virtual environment (.venv_linux)..."
    python3 -m venv .venv_linux
fi

source .venv_linux/bin/activate

echo "Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Cleaning previous builds..."
rm -rf build/linux dist/linux

echo "Running PyInstaller..."
python -m PyInstaller --clean --noconfirm --distpath dist/linux --workpath build/linux build_linux.spec

echo "Packaging Linux artifact..."
cd dist/linux
if [ -f "ModularSpriteEditor" ]; then
    tar -czf ModularSpriteEditor-linux.tar.gz ModularSpriteEditor
elif [ -d "ModularSpriteEditor" ]; then
    tar -czf ModularSpriteEditor-linux.tar.gz ModularSpriteEditor
else
    echo "Error: Could not find Linux build output in dist/linux"
    exit 1
fi

echo "Build complete. Artifact located at dist/linux/ModularSpriteEditor-linux.tar.gz"
