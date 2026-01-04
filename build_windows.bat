@echo off
REM Windows Build Script

REM 1. Activate venv (Assume existing .venv)
call .venv\Scripts\activate.bat

REM 2. Run PyInstaller
pyinstaller --clean --noconfirm build_windows.spec

echo Build complete. Executable located at dist\ModularSpriteEditor\ModularSpriteEditor.exe
pause
