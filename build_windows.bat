@echo off
setlocal EnableDelayedExpansion
REM Windows Build Script for ModularSpriteEditor

echo Checking for Python...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3 and add it to PATH.
    pause
    exit /b
)

if exist .venv_win (
    if not exist ".venv_win\Scripts\activate.bat" (
        echo [WARNING] Found broken virtual environment. Removing...
        rmdir /s /q .venv_win
        goto :create_venv
    )
    goto :venv_exists
)

:create_venv
echo Creating virtual environment (with --copies for shared drive compatibility)...
python -m venv .venv_win --copies
if %errorlevel% neq 0 goto :venv_error
goto :activate

:venv_exists
echo Virtual environment found and looks valid.

:activate
call .venv_win\Scripts\activate.bat
if %errorlevel% neq 0 goto :venv_broken

echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b
)

echo Cleaning previous builds...
if exist build\windows rmdir /s /q build\windows
if exist dist\windows rmdir /s /q dist\windows

echo.
echo [INFO] Shared Drive detected. Building in local TEMP folder to avoid permission errors...
set "BUILD_ROOT=%TEMP%\ModularSpriteEditor_Build"
if exist "%BUILD_ROOT%" rmdir /s /q "%BUILD_ROOT%"
mkdir "%BUILD_ROOT%"

echo Running PyInstaller (Output to %BUILD_ROOT%)...
python -m PyInstaller --clean --noconfirm --distpath "%BUILD_ROOT%\dist" --workpath "%BUILD_ROOT%\build" build_windows.spec
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller failed.
    pause
    exit /b
)

echo.
echo Copying artifacts back to project folder...
mkdir dist\windows
copy /Y "%BUILD_ROOT%\dist\ModularSpriteEditor.exe" "dist\windows\ModularSpriteEditor.exe"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy build artifacts back to Z:.
    echo The build is available at: %BUILD_ROOT%\dist\ModularSpriteEditor.exe
    pause
    exit /b
)

echo.
echo ==========================================
echo Build complete!
echo Cleaning up temp files...
rmdir /s /q "%BUILD_ROOT%"
echo Executable: dist\windows\ModularSpriteEditor.exe
echo ==========================================
pause
exit /b

:venv_error
echo.
echo [ERROR] Failed to create virtual environment.
echo This often happens on Shared Drives (Z:).
echo Please COPY the project to C:\ and try again.
pause
exit /b

:venv_broken
echo.
echo [ERROR] Virtual environment is broken or missing scripts.
echo Automatic repair failed. Please delete .venv manually.
pause
exit /b
