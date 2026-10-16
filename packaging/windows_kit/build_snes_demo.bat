@echo off
rem Build the SNES demo ROM (examples\snes\snes_demo\modular_sprite_snes_demo.sfc) with the PVSnesLib that comes with
rem it, through examples\snes\snes_demo\build_windows.ps1 (Windows PowerShell: no make or MSYS2 needed).
setlocal
set "CALLER=%~1"
set "RESULT=1"
set "PVSNESLIB_HOME=%~dp0examples\snes\snes_demo\third_party\pvsneslib"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0examples\snes\snes_demo\build_windows.ps1"
if errorlevel 1 (
    echo.
    echo The build failed, see above.
    goto :end
)
echo.
echo ROM: %~dp0examples\snes\snes_demo\modular_sprite_snes_demo.sfc - open it in a SNES emulator.
set "RESULT=0"

:end
rem Keep a double-clicked window open; not when called with "nopause", nor on CI.
if /i not "%CALLER%"=="nopause" if not defined CI pause
exit /b %RESULT%
