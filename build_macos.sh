#!/bin/bash
# MacOS Build Script

# 1. Activate venv
source .venv/bin/activate

# 2. Run PyInstaller
python3 -m PyInstaller --clean --noconfirm build_mac.spec

echo "Build complete. App located at dist/ModularSpriteEditor.app"
