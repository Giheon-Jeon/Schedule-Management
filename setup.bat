@echo off
chcp 65001 >nul
REM ====================================================================
REM  주간 일정 위젯 - 설치 (한 번만 실행)
REM   1) 부팅 시 자동 시작 등록
REM   2) 지금 바로 위젯 실행
REM  이후 깃허브에 올라온 변경사항은 위젯이 켜질 때 자동으로 반영됩니다.
REM ====================================================================
setlocal
set "APPDIR=%~dp0"
set "SCRIPT=%APPDIR%schedule_widget.pyw"

REM pythonw.exe 경로 탐색
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo [오류] Python(pythonw)을 찾을 수 없습니다. https://www.python.org 에서 설치 후 다시 실행하세요.
  pause
  exit /b 1
)

echo [1/2] 자동 시작 등록 중...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut([System.IO.Path]::Combine($ws.SpecialFolders('Startup'),'주간일정위젯.lnk'));" ^
  "$lnk.TargetPath = '%PYW%';" ^
  "$lnk.Arguments = '\"%SCRIPT%\"';" ^
  "$lnk.WorkingDirectory = '%APPDIR%';" ^
  "$lnk.WindowStyle = 7;" ^
  "$lnk.Description = '주간 일정 위젯';" ^
  "$lnk.Save();"

echo [2/2] 위젯 실행 중...
start "" "%PYW%" "%SCRIPT%"

echo.
echo 설치 완료! 우측 하단에 위젯이 떴는지 확인하세요.
echo (자동 시작 해제: uninstall_autostart.bat)
timeout /t 3 >nul
