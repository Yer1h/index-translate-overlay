@echo off
rem Запуск Index-Translate Overlay (трей, без консоли)
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    py -3.12 -m venv .venv || goto :err
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :err
)
start "" ".venv\Scripts\pythonw.exe" -m app.main
exit /b 0
:err
echo Ошибка подготовки окружения. Проверь, что установлен Python 3.12 (py -3.12)
pause
