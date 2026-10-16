@echo off
rem Export a project into the SNES demo (all mappings) and build the ROM.
rem   export_to_snes.bat [project.json]     or drag a project .json onto this file
rem Without a project it exports examples\sgdk\PoP_WW.json. A project needs at most 512 sprite tiles for the SNES.
setlocal
if "%~1"=="" (set "PROJECT=%~dp0examples\sgdk\PoP_WW.json") else (set "PROJECT=%~f1")
set "RESULT=1"
cd /d "%~dp0"
"%~dp0export_snes.exe" --project-json "%PROJECT%" --output-dir "%~dp0examples\snes\snes_demo" --mapping all
if errorlevel 1 (
    echo.
    echo The export failed, see above.
    goto :end
)
call "%~dp0build_snes_demo.bat" nopause
if not errorlevel 1 set "RESULT=0"

:end
rem Keep a double-clicked window open, not on CI.
if not defined CI pause
exit /b %RESULT%
