@echo off
rem Build the SGDK demo ROM (examples\megadrive\megadrive_demo\out\debug\rom.bin) with the SGDK that comes with it.
rem SGDK's resource compiler needs Java.
setlocal
set "CALLER=%~1"
set "RESULT=1"
cd /d "%~dp0examples\megadrive\megadrive_demo"
where java >nul 2>nul
if errorlevel 1 (
    echo Java was not found. SGDK's resource compiler needs it: install a Java runtime and try again.
    goto :end
)
rem SGDK's tools first on the PATH: GCC's link-time optimiser runs "make" again by name.
set "PATH=%CD%\third_party\sgdk\bin;%PATH%"
make debug
if errorlevel 1 (
    echo.
    echo The build failed, see above. Is the folder path free of spaces?
    goto :end
)
echo.
echo ROM: %CD%\out\debug\rom.bin - open it in a Mega Drive emulator.
set "RESULT=0"

:end
rem Keep a double-clicked window open; not when export_to_megadrive.bat calls this, nor on CI.
if /i not "%CALLER%"=="nopause" if not defined CI pause
exit /b %RESULT%
