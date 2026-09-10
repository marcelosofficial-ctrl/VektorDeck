@echo off
setlocal
cd /d "%~dp0"
title VEKTORDECK REPAIR
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\repair.ps1"
if errorlevel 1 (
  echo.
  echo Repair failed. Read the message above, then press any key.
  pause >nul
)
endlocal
