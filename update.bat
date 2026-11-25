@echo off
REM Weekly Schedule Widget - manual update (pull latest from GitHub + relaunch)
REM Normally handled automatically on widget start, or via the widget's refresh button.
setlocal
set "APPDIR=%~dp0"
cd /d "%APPDIR%"
echo Checking GitHub for updates...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [WARN] Update failed. If you edited code locally there may be a conflict.
  pause
  exit /b 1
)
set "PYW="
for /f "delims=" %%i in ('python -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not exist "%PYW%" set "PYW="
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
start "" "%PYW%" "%APPDIR%schedule_widget.pyw"
echo Done. Relaunched latest version.
timeout /t 2 >nul
