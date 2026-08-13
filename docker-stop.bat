@echo off
setlocal EnableExtensions
title Household Money - Docker stop
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money - stop Docker
echo  ============================================
echo.
echo  This stops the container. Your data folder stays.
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker was not found.
  pause
  exit /b 1
)

docker compose down
if errorlevel 1 (
  echo  [ERROR] Could not stop the container.
  pause
  exit /b 1
)

echo.
echo  Stopped. Start again with docker-start.bat
echo.
pause
endlocal
