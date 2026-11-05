@echo off
setlocal
title Pocket Agent - Setup
cd /d "%~dp0.."

echo.
echo  ============================================
echo    Pocket Agent - one-time setup
echo  ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  Python was not found.
  echo.
  echo  1^) Install Python from https://www.python.org/downloads/
  echo  2^) IMPORTANT: tick "Add python.exe to PATH" on the first screen
  echo  3^) Run this setup.bat again
  echo.
  pause
  exit /b 1
)

echo  Creating a private virtual environment in .venv ...
python -m venv .venv
if errorlevel 1 goto fail

echo  Installing packages (this needs internet, ~1 minute) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Some optional packages failed. Trying the essentials only...
  ".venv\Scripts\python.exe" -m pip install google-genai PyQt6 SpeechRecognition pyttsx3
  if errorlevel 1 goto fail
  echo.
  echo  Extras were skipped - Pocket still runs. Later you can retry with:
  echo    .venv\Scripts\pip install SpeechRecognition pyttsx3
)

echo.
echo  Done. Now get your FREE Gemini key:
echo    https://aistudio.google.com/apikey
echo  Then double-click start.bat and paste the key into Settings.
echo.
pause
exit /b 0

:fail
echo.
echo  Setup failed. Copy the error above if you need help.
pause
exit /b 1
