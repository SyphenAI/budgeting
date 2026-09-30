@echo off
setlocal EnableExtensions
title Household Money - Update and start
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money - Update and start
echo  ============================================
echo.
echo  This stops the app, downloads the latest from GitHub,
echo  then starts it again. Your data folder stays.
echo.

where docker >nul 2>&1
if not errorlevel 1 (
  echo  Stopping the app if it is running...
  docker compose stop >nul 2>&1
)

call "%~dp0update.bat" /auto
if errorlevel 1 (
  echo.
  echo  Update did not finish. Your budget was not erased.
  echo  Check internet, then try this file again.
  pause
  exit /b 1
)

echo.
echo  Starting Household Money...
if exist "%~dp0docker-start.bat" (
  call "%~dp0docker-start.bat"
) else (
  echo  Could not find docker-start.bat. Start the app the usual way, then Ctrl+F5.
  pause
)
endlocal
