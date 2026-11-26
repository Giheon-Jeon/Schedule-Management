@echo off
REM ====================================================================
REM  Weekly Schedule Widget - one-time setup
REM   0) if downloaded as ZIP (no .git): link the folder to GitHub so
REM      auto-update works
REM   1) register autostart (runs at boot, no console window)
REM   2) launch the widget now
REM ====================================================================
setlocal

REM --- run from a temp copy: step 0 may rewrite this very file, and cmd
REM     misbehaves when the running batch file changes underneath it ---
if /i not "%~1"=="--from-temp" (
  copy /y "%~f0" "%TEMP%\schedule_widget_setup.bat" >nul
  "%TEMP%\schedule_widget_setup.bat" --from-temp "%~dp0"
)
set "APPDIR=%~2"
set "SCRIPT=%APPDIR%schedule_widget.pyw"
set "REPO=https://github.com/Giheon-Jeon/Schedule-Management.git"

REM --- resolve pythonw.exe (prefer the real path, not the Store alias) ---
set "PYW="
for /f "delims=" %%i in ('python -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not exist "%PYW%" set "PYW="
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [ERROR] Python was not found. Install Python from https://www.python.org and retry.
  pause
  exit /b 1
)
echo Using: %PYW%

REM --- 0) ZIP download has no .git: connect it to GitHub for auto-update ---
if not exist "%APPDIR%.git" (
  where git >nul 2>nul
  if errorlevel 1 (
    echo [WARN] Git was not found - the widget works, but auto-update is off.
    echo        Install Git from https://git-scm.com and run setup.bat again.
  ) else (
    echo [0/2] Linking this folder to GitHub for auto-update...
    pushd "%APPDIR%"
    git init -q
    git remote add origin %REPO%
    git fetch -q origin main && git checkout -q -f -B main origin/main
    if errorlevel 1 (
      rmdir /s /q .git
      echo [WARN] Could not reach GitHub - auto-update is off. Run setup.bat again when online.
    )
    popd
  )
)

echo [1/2] Registering autostart...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $lnk=$ws.CreateShortcut((Join-Path $ws.SpecialFolders('Startup') 'ScheduleWidget.lnk')); $lnk.TargetPath='%PYW%'; $lnk.Arguments='\"%SCRIPT%\"'; $lnk.WorkingDirectory='%APPDIR%'; $lnk.WindowStyle=7; $lnk.Description='Weekly Schedule Widget'; $lnk.Save()"

echo [2/2] Launching widget...
REM Start-Process (ShellExecute) so the widget does not inherit this console's
REM output pipe - otherwise "irm ... | iex" would wait until the widget exits
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYW%' -ArgumentList '\"%SCRIPT%\"' -WorkingDirectory '%APPDIR%'"

echo.
echo Done. Look at the BOTTOM-RIGHT corner of your screen.
echo   - Bring it to front any time: Ctrl+Alt+W
echo   - To disable autostart, run uninstall_autostart.bat
timeout /t 5 >nul
exit /b 0
