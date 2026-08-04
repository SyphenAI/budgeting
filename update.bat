@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Household Money - Update
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money - Update
echo  ============================================
echo.
echo  This downloads the latest app files from:
echo    https://github.com/SyphenAI/budgeting
echo.
echo  It will KEEP your money data (the data folder).
echo  It will NOT change your password or budget entries.
echo.
echo  Windows may ask for permission. If Defender blocks
echo  this, right-click update.bat -^> Run as administrator.
echo.
echo  Press Ctrl+C to cancel, or
pause

REM --- Need PowerShell (built into Windows) ---
where powershell >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] PowerShell not found. Cannot auto-update on this PC.
  echo  Instead: download a fresh ZIP from GitHub and copy your data folder over.
  pause
  exit /b 1
)

set "APP_DIR=%~dp0"
set "ZIP=%TEMP%\household-money-update.zip"
set "EXTRACT=%TEMP%\household-money-update"
set "REPO_ZIP_URL=https://github.com/SyphenAI/budgeting/archive/refs/heads/main.zip"

if exist "%APP_DIR%VERSION" (
  set /p CUR_VER=<"%APP_DIR%VERSION"
  echo  Current version file: !CUR_VER!
) else (
  echo  Current version file: unknown
)
echo.

echo  [1/4] Downloading latest app...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {" ^
  "  $ProgressPreference='SilentlyContinue';" ^
  "  Invoke-WebRequest -Uri '%REPO_ZIP_URL%' -OutFile '%ZIP%' -UseBasicParsing;" ^
  "  if (-not (Test-Path '%ZIP%')) { exit 1 };" ^
  "  exit 0" ^
  "} catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
  echo  [ERROR] Download failed. Check your internet connection and try again.
  echo  Or open https://github.com/SyphenAI/budgeting and use Code -^> Download ZIP manually.
  pause
  exit /b 1
)

echo  [2/4] Unpacking...
if exist "%EXTRACT%" rmdir /s /q "%EXTRACT%" >nul 2>&1
mkdir "%EXTRACT%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try {" ^
  "  Expand-Archive -Path '%ZIP%' -DestinationPath '%EXTRACT%' -Force;" ^
  "  exit 0" ^
  "} catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 (
  echo  [ERROR] Could not unpack the download.
  pause
  exit /b 1
)

REM GitHub ZIP extracts to budgeting-main\...
set "SRC="
for /d %%D in ("%EXTRACT%\*") do (
  if exist "%%D\backend\app\main.py" set "SRC=%%D"
  if exist "%%D\start.bat" if exist "%%D\backend" set "SRC=%%D"
)
if not defined SRC (
  echo  [ERROR] Could not find app files inside the download.
  pause
  exit /b 1
)

echo  [3/4] Copying new files (keeping your data folder)...
REM Pass paths via env (handles spaces). Never overwrite data/, .venv/, secrets.
set "UPD_SRC=%SRC%"
set "UPD_DST=%APP_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$src = $env:UPD_SRC; $dst = $env:UPD_DST;" ^
  "if (-not $src -or -not (Test-Path $src)) { Write-Host 'Source missing'; exit 1 };" ^
  "$excludeDirs = @('.git','.venv','data','private','__pycache__');" ^
  "$excludeFiles = @('github_pat.txt','.env','budget.db');" ^
  "function Copy-Tree([string]$from, [string]$to) {" ^
  "  if (-not (Test-Path -LiteralPath $to)) { New-Item -ItemType Directory -Path $to -Force | Out-Null }" ^
  "  Get-ChildItem -LiteralPath $from -Force | ForEach-Object {" ^
  "    $name = $_.Name;" ^
  "    if ($_.PSIsContainer) {" ^
  "      if ($excludeDirs -contains $name) { return }" ^
  "      Copy-Tree $_.FullName (Join-Path $to $name)" ^
  "    } else {" ^
  "      if ($excludeFiles -contains $name) { return }" ^
  "      if ($name -like '*.db') { return }" ^
  "      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $to $name) -Force" ^
  "    }" ^
  "  }" ^
  "};" ^
  "try { Copy-Tree $src $dst; Write-Host 'Copy complete'; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"

if errorlevel 1 (
  echo  [ERROR] Copy failed. Your data folder was not deleted.
  pause
  exit /b 1
)

echo  [4/4] Refreshing app tools (safe to re-run)...
if exist "%APP_DIR%.venv\Scripts\python.exe" (
  "%APP_DIR%.venv\Scripts\python.exe" -m pip install -r "%APP_DIR%backend\requirements.txt" -q
  if errorlevel 1 (
    echo  Package refresh had a problem. Run install.bat once if the app will not start.
  ) else (
    echo  Packages updated.
  )
) else (
  echo  No install found yet. Run install.bat next.
)

if exist "%APP_DIR%VERSION" (
  set /p NEW_VER=<"%APP_DIR%VERSION"
  echo  Updated version file: !NEW_VER!
)

echo.
echo  ============================================
echo   Update finished
echo  ============================================
echo.
echo  Your budget data was kept in the data folder.
echo.
echo  Next:
echo    1. Close ALL Household Money windows completely
echo    2. Right-click start.bat -^> Run as administrator
echo    3. In the browser press Ctrl+F5 (hard refresh) so old pages clear
echo    4. Sign in as usual
echo.
echo  Import should say Chase PDF is available (version file in this folder).
echo  If start fails, run install.bat once, then start.bat.
echo.
del "%ZIP%" >nul 2>&1
rmdir /s /q "%EXTRACT%" >nul 2>&1
pause
endlocal
