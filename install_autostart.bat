@echo off
REM ====================================================================
REM  주간 일정 위젯 - 자동 시작 등록
REM  Windows 시작프로그램 폴더에 바로가기를 만들어 부팅 시 자동 실행
REM  (pythonw.exe 로 실행하므로 콘솔 창이 뜨지 않습니다)
REM ====================================================================
setlocal

set "APPDIR=%~dp0"
set "SCRIPT=%APPDIR%schedule_widget.pyw"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"

REM Microsoft Store 버전 Python 경로 자동 탐색
for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYW=%%i"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$lnk = $ws.CreateShortcut([System.IO.Path]::Combine($ws.SpecialFolders('Startup'),'주간일정위젯.lnk'));" ^
  "$lnk.TargetPath = '%PYW%';" ^
  "$lnk.Arguments = '\"%SCRIPT%\"';" ^
  "$lnk.WorkingDirectory = '%APPDIR%';" ^
  "$lnk.WindowStyle = 7;" ^
  "$lnk.Description = '주간 일정 위젯';" ^
  "$lnk.Save();" ^
  "Write-Host ('등록 완료: ' + [System.IO.Path]::Combine($ws.SpecialFolders('Startup'),'주간일정위젯.lnk'))"

echo.
echo 다음 부팅부터 자동으로 실행됩니다. 지금 바로 실행하려면 start_widget.bat 를 더블클릭하세요.
pause
