@echo off
REM 주간 일정 위젯 - 자동 시작 해제
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$p = [System.IO.Path]::Combine($ws.SpecialFolders('Startup'),'주간일정위젯.lnk');" ^
  "if (Test-Path $p) { Remove-Item $p -Force; Write-Host '자동 시작 해제 완료' } else { Write-Host '등록된 바로가기가 없습니다' }"
pause
