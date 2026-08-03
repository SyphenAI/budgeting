@echo off
setlocal EnableExtensions
title Household Money - First-time setup
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money - First-time setup
echo  ============================================
echo.
echo  This will install what the app needs on THIS computer.
echo  You only need to do this once.
echo.
echo  Please leave this window open until it says DONE.
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Python was not found.
  echo.
  echo  Please install Python first:
  echo    1. Open https://www.python.org/downloads/
  echo    2. Download and run the Windows installer
  echo    3. IMPORTANT: check the box "Add python.exe to PATH"
  echo    4. Finish install, then run this file again
  echo.
  pause
  exit /b 1
)

echo  [1/3] Creating app folder tools...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo  [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
  )
) else (
  echo        Already created - skipping.
)

echo  [2/3] Installing app packages (may take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 (
  echo  [ERROR] Package install failed. Check your internet connection and try again.
  pause
  exit /b 1
)

echo  [3/3] Creating a desktop shortcut to Start Household Money...
set "START_BAT=%~dp0start.bat"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT=%DESKTOP%\Household Money.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%START_BAT%'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 1; $s.Description = 'Start Household Money budget app'; $s.Save()"

echo.
echo  ============================================
echo   DONE - setup finished
echo  ============================================
echo.
echo  Next steps:
echo    1. Double-click "start.bat" in this folder
echo       OR use the "Household Money" icon on your Desktop
echo    2. A browser window should open
echo    3. Sign in with:
echo         Username: admin
echo         Password: admin
echo    4. The app will ask you to choose a NEW password
echo.
echo  Your money data stays on this computer only.
echo.
pause
endlocal
