@echo off
REM Weekly Schedule Widget - remove autostart
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $p=Join-Path $ws.SpecialFolders('Startup') 'ScheduleWidget.lnk'; if (Test-Path $p) { Remove-Item $p -Force; Write-Host 'Autostart removed.' } else { Write-Host 'No autostart shortcut found.' }"
pause
