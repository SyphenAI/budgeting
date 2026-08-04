@echo off
setlocal EnableExtensions
title Household Money
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money
echo  ============================================
echo.

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo  Setup has not been run yet on THIS folder.
  echo.
  echo  1. Double-click install.bat first
  echo  2. Wait until it says DONE
  echo  3. Then double-click start.bat again
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0backend\app\main.py" (
  echo  [ERROR] App files are missing from this folder.
  echo  Use the folder that contains install.bat, start.bat, and the backend folder.
  echo.
  pause
  exit /b 1
)

REM Free port 8787 if a leftover process is stuck
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":8787" ^| findstr "LISTENING"') do (
  echo  Clearing old app still using port 8787...
  taskkill /PID %%P /F >nul 2>&1
)

echo  Starting the app... please wait.
echo  A second window will open - leave that one running.
echo.

REM Launch server via a simple helper bat (avoids Windows quoting bugs with python.exe)
start "Household Money - keep open" /D "%~dp0" cmd /c "%~dp0start-server.bat"

REM Wait until the app answers (up to ~60 seconds)
set /a tries=0
:waitloop
set /a tries+=1
if %tries% GTR 60 goto notready

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8787/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 goto ready

timeout /t 1 /nobreak >nul
goto waitloop

:notready
echo.
echo  ============================================
echo   The app did not start in time
echo  ============================================
echo.
echo  Check the other window for error messages.
echo  Then try:
echo    1. Close all Household Money windows
echo    2. Double-click install.bat
echo    3. Double-click start.bat
echo.
start "" "http://127.0.0.1:8787"
pause
exit /b 1

:ready
echo  App is ready. Opening your browser...
echo.
start "" "http://127.0.0.1:8787"

echo  ============================================
echo   Household Money is running
echo  ============================================
echo.
echo  Address:  http://127.0.0.1:8787
echo.
echo  First login (until you change it):
echo    Username: admin
echo    Password: admin
echo.
echo  Keep the other window open while you use the app.
echo  You can close THIS window now.
echo.
pause
endlocal
