@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Agent Envoy needs its Python environment first. Run these once, in this folder:
  echo.
  echo      python -m venv .venv
  echo      .venv\Scripts\python -m pip install -r requirements.txt
  echo.
  echo  Then double-click this file again. Details are in README.md, "Quick start".
  echo.
  pause
  exit /b 1
)

.venv\Scripts\python envoy.py
pause
