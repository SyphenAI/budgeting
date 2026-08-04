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
echo  NOTE: If Windows Defender blocks this, right-click
echo  install.bat and choose "Run as administrator".
echo  SmartScreen: More info -^> Run anyway.
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

echo  [3/3] Creating a desktop shortcut with app logo...
set "APP_DIR=%~dp0"
set "START_BAT=%~dp0start.bat"
set "APP_ICON=%~dp0brand\assets\household-money.ico"
set "SHORTCUT_OK=0"

if not exist "%APP_ICON%" (
  echo        Logo icon file missing - shortcut will use default icon.
)

REM Resolve real Desktop (OneDrive-aware) and create shortcut with logo
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$startBat = $env:START_BAT; $icon = $env:APP_ICON; $appDir = $env:APP_DIR;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$targets = @();" ^
  "if ($desktop -and (Test-Path $desktop)) { $targets += (Join-Path $desktop 'Household Money.lnk') };" ^
  "$targets += (Join-Path $appDir 'Household Money.lnk');" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$made = $false;" ^
  "foreach ($path in $targets) {" ^
  "  try {" ^
  "    $s = $ws.CreateShortcut($path);" ^
  "    $s.TargetPath = $startBat;" ^
  "    $s.WorkingDirectory = $appDir;" ^
  "    $s.WindowStyle = 1;" ^
  "    $s.Description = 'Household Money budget app';" ^
  "    if ($icon -and (Test-Path $icon)) { $s.IconLocation = $icon + ',0' };" ^
  "    $s.Save();" ^
  "    if (Test-Path $path) { Write-Output ('CREATED:' + $path); $made = $true; break }" ^
  "  } catch { }" ^
  "};" ^
  "if (-not $made) { exit 1 }"

if errorlevel 1 (
  echo        Shortcut could not be created - that is OK. Use start.bat instead.
) else (
  set "SHORTCUT_OK=1"
  echo        Shortcut created with app logo.
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
