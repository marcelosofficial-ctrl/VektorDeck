@echo off
setlocal
cd /d "%~dp0"
title VEKTORDECK DIAGNOSTICS
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\diagnostics.ps1"
if errorlevel 1 (
  echo.
  echo Diagnostics failed. Read the message above, then press any key.
  pause >nul
)
endlocal
