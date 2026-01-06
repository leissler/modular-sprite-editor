@echo off
:: Batch script to clear Windows Icon Cache
echo.
echo ==============================================
echo      Windows Icon Cache Refresher
echo ==============================================
echo.
echo [!] This will close File Explorer temporarily.
echo [!] Please save any open work in other folders.
echo.
pause

echo.
echo 1. Stopping Windows Explorer...
taskkill /f /im explorer.exe

echo.
echo 2. Clearing Icon Cache...
cd /d %userprofile%\AppData\Local\Microsoft\Windows\Explorer
del /f /q iconcache_*.db
del /f /q thumbcache_*.db

:: Also the legacy one just in case
del /f /q "%localappdata%\IconCache.db" 2>nul

echo.
echo 3. Restarting Explorer...
start explorer.exe

echo.
echo ==============================================
echo                Done!
echo ==============================================
echo If icons are still wrong, a full reboot may be required.
echo.
pause
