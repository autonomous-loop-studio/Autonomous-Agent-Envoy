@echo off
setlocal
set LLAMA=C:\Users\anonb\.unsloth\llama.cpp\build\bin\Release\llama-server.exe
set MODEL=%~dp0ALS-MYTHOS-4B-heretic-f16.gguf

if not exist "%LLAMA%"  echo llama-server not found: %LLAMA% & pause & exit /b 1
if not exist "%MODEL%"  echo model not found: %MODEL% & pause & exit /b 1

echo Model server: http://127.0.0.1:58880/v1
echo Website:      http://localhost:8080/router/
echo (close this window to stop the server)
echo.

"%LLAMA%" -m "%MODEL%" -ngl 99 -c 32768 -fa on -t 8 ^
  --host 127.0.0.1 --port 58880 ^
  -np 1 ^
  --reasoning off

pause
