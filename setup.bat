@echo off
rem Первичная установка Index-Translate Overlay:
rem   1) venv + зависимости
rem   2) llama.cpp (CUDA-сборка) -> bin\
rem   3) модель Index-Translate-2B Q6_K + vision-веса (mmproj) -> models\
setlocal
cd /d "%~dp0"

echo === [1/3] Python-окружение
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv || goto :err
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :err
)

echo === [2/3] llama.cpp (CUDA 12.4, ~530 МБ)
if not exist "bin\llama-server.exe" (
    curl -L --retry 3 -o llama.zip "https://github.com/ggml-org/llama.cpp/releases/download/b11871/llama-b11871-bin-win-cuda-12.4-x64.zip" || goto :err
    curl -L --retry 3 -o cudart.zip "https://github.com/ggml-org/llama.cpp/releases/download/b11871/cudart-llama-bin-win-cuda-12.4-x64.zip" || goto :err
    tar -xf llama.zip -C bin 2>nul || mkdir bin && tar -xf llama.zip -C bin || goto :err
    tar -xf cudart.zip -C bin || goto :err
    del llama.zip cudart.zip
)

echo === [3/3] Модель Index-Translate-2B (~2 ГБ)
if not exist "models\Index-Translate-2B.Q6_K.gguf" (
    if not exist models mkdir models
    curl -L --retry 3 -o "models\Index-Translate-2B.Q6_K.gguf" "https://huggingface.co/IndexTeam/Index-Translate-2B-GGUF/resolve/main/Index-Translate-2B.Q6_K.gguf" || goto :err
    curl -L --retry 3 -o "models\Index-Translate-2B.mmproj-Q8_0.gguf" "https://huggingface.co/IndexTeam/Index-Translate-2B-GGUF/resolve/main/Index-Translate-2B.mmproj-Q8_0.gguf" || goto :err
)

echo.
echo Готово! Запуск: start.bat
exit /b 0
:err
echo Ошибка установки. Проверь интернет и что py -3.12 доступен.
pause
exit /b 1
