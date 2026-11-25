@echo off
REM Weekly Schedule Widget - run now (no console window)
setlocal
set "APPDIR=%~dp0"
set "PYW="
for /f "delims=" %%i in ('python -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not exist "%PYW%" set "PYW="
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [ERROR] pythonw not found.
  pause
  exit /b 1
)
start "" "%PYW%" "%APPDIR%schedule_widget.pyw"
