@echo off
REM ====================================================================
REM  Weekly Schedule Widget - one-time setup
REM   1) register autostart (runs at boot, no console window)
REM   2) launch the widget now
REM  Future changes pushed to GitHub are auto-applied when the widget starts.
REM ====================================================================
setlocal
set "APPDIR=%~dp0"
set "SCRIPT=%APPDIR%schedule_widget.pyw"

REM --- resolve pythonw.exe (prefer the real path, not the Store alias) ---
set "PYW="
for /f "delims=" %%i in ('python -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not exist "%PYW%" set "PYW="
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [ERROR] pythonw not found. Install Python from https://www.python.org and retry.
  pause
  exit /b 1
)
echo Using: %PYW%

echo [1/2] Registering autostart...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $lnk=$ws.CreateShortcut((Join-Path $ws.SpecialFolders('Startup') 'ScheduleWidget.lnk')); $lnk.TargetPath='%PYW%'; $lnk.Arguments='\"%SCRIPT%\"'; $lnk.WorkingDirectory='%APPDIR%'; $lnk.WindowStyle=7; $lnk.Description='Weekly Schedule Widget'; $lnk.Save()"

echo [2/2] Launching widget...
start "" "%PYW%" "%SCRIPT%"

echo.
echo Done. Look at the BOTTOM-RIGHT corner of your screen.
echo (To disable autostart, run uninstall_autostart.bat)
timeout /t 4 >nul
