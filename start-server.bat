@echo off
REM Internal launcher - keeps the server window open and shows errors clearly.
setlocal EnableExtensions
title Household Money - keep open
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo.
  echo  [ERROR] Python tools not found in this folder.
  echo  Double-click install.bat first, then try start.bat again.
  echo.
  pause
  exit /b 1
)

echo.
echo  Household Money server
echo  ----------------------
echo  Folder: %cd%
echo  Do not close this window while using the app.
echo  When finished, close this window to stop the app.
echo.
echo  Starting on http://127.0.0.1:8787 ...
echo.

"%PY%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787

echo.
echo  Server stopped.
if errorlevel 1 (
  echo  Something went wrong while starting.
  echo  Try running install.bat again, then start.bat.
)
echo.
pause
endlocal
