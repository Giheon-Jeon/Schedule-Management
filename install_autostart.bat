@echo off
REM Weekly Schedule Widget - register autostart only
setlocal
set "APPDIR=%~dp0"
set "SCRIPT=%APPDIR%schedule_widget.pyw"
set "PYW="
for /f "delims=" %%i in ('python -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not exist "%PYW%" set "PYW="
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [ERROR] pythonw not found.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $lnk=$ws.CreateShortcut((Join-Path $ws.SpecialFolders('Startup') 'ScheduleWidget.lnk')); $lnk.TargetPath='%PYW%'; $lnk.Arguments='\"%SCRIPT%\"'; $lnk.WorkingDirectory='%APPDIR%'; $lnk.WindowStyle=7; $lnk.Description='Weekly Schedule Widget'; $lnk.Save(); Write-Host 'Registered autostart.'"
pause
