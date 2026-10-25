@echo off
rem Запуск с консолью для отладки (логи также пишутся в logs\app.log)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m app.main
pause
