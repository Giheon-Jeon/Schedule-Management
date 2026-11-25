@echo off
chcp 65001 >nul
REM 주간 일정 위젯 - 수동 업데이트 (깃허브 최신 버전 받기 + 재실행)
REM  보통은 위젯이 켜질 때 또는 위젯의 ↻ 버튼으로 자동 처리되므로 쓸 일이 거의 없습니다.
setlocal
set "APPDIR=%~dp0"
cd /d "%APPDIR%"

echo 깃허브에서 최신 버전 확인 중...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [알림] 업데이트에 실패했습니다. 로컬에서 코드를 직접 수정한 경우 충돌일 수 있습니다.
  pause
  exit /b 1
)

set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
start "" "%PYW%" "%APPDIR%schedule_widget.pyw"
echo 완료! 최신 버전으로 실행했습니다.
timeout /t 2 >nul
