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

if not exist "backend\requirements.txt" (
  echo  [ERROR] Cannot find backend\requirements.txt
  echo  You may have opened the wrong folder.
  echo  Open the folder that contains install.bat, backend, and frontend.
  echo.
  pause
  exit /b 1
)

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Python was not found.
  echo.
  echo  Please install Python first:
  echo    1. Open https://www.python.org/downloads/
  echo    2. Download and run the Windows installer
  echo    3. IMPORTANT: check the box "Add python.exe to PATH"
  echo    4. Finish install, then double-click install.bat again
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

echo  [3/3] Creating a desktop shortcut (optional)...
set "START_BAT=%~dp0start.bat"
set "SHORTCUT_OK=0"

REM Resolve real Desktop (OneDrive-aware)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"

if defined DESKTOP if exist "%DESKTOP%" (
  set "SHORTCUT=%DESKTOP%\Household Money.lnk"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut($env:SHORTCUT); $s.TargetPath = $env:START_BAT; $s.WorkingDirectory = (Split-Path -Parent $env:START_BAT); $s.WindowStyle = 1; $s.Description = 'Start Household Money'; $s.Save(); exit 0 } catch { exit 1 }" 2>nul
  if not errorlevel 1 (
    if exist "%DESKTOP%\Household Money.lnk" set "SHORTCUT_OK=1"
  )
)

REM Fallback: shortcut inside this app folder
if "%SHORTCUT_OK%"=="0" (
  set "SHORTCUT=%~dp0Household Money.lnk"
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%START_BAT%'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 1; $s.Description = 'Start Household Money'; $s.Save(); exit 0 } catch { exit 1 }" 2>nul
  if exist "%~dp0Household Money.lnk" (
    set "SHORTCUT_OK=1"
    echo        Desktop shortcut skipped - created "Household Money.lnk" in this folder instead.
  ) else (
    echo        Shortcut could not be created - that is OK. Use start.bat instead.
  )
) else (
  echo        Desktop shortcut created: Household Money
)

echo.
echo  ============================================
echo   DONE - setup finished
echo  ============================================
echo.
echo  Next steps:
echo    1. Double-click start.bat in this folder
if "%SHORTCUT_OK%"=="1" echo       (or the Household Money shortcut if you see one)
echo    2. Wait until it says the app is ready
echo    3. Browser should open to http://127.0.0.1:8787
echo    4. Sign in with:
echo         Username: admin
echo         Password: admin
echo    5. Choose a NEW password when asked
echo.
echo  Keep the "Household Money - keep open" window running while you use the app.
echo  Your money data stays on this computer only.
echo.
pause
endlocal
