@echo off
REM 주간 일정 위젯 - 지금 바로 실행 (콘솔 창 없이)
set "APPDIR=%~dp0"
set "PYW=pythonw"
for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYW=%%i"
start "" "%PYW%" "%APPDIR%schedule_widget.pyw"
