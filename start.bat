@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\pythonw.exe" (
  echo Pocket Agent is not installed yet. Run setup.bat first.
  pause
  exit /b 1
)

REM Starts with no console window. Errors go to error.log
start "" ".venv\Scripts\pythonw.exe" app.py
if errorlevel 1 (
  ".venv\Scripts\python.exe" app.py 2>> error.log
  echo Crash details saved in error.log
  pause
)
