@echo off
setlocal
cd /d "%~dp0"
title VEKTORDECK UPDATE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update.ps1"
if errorlevel 1 (
  echo.
  echo Update failed. Read the message above, then press any key.
  pause >nul
)
endlocal
