@echo off
setlocal EnableExtensions
title Household Money
cd /d "%~dp0"

echo.
echo  ============================================
echo   Household Money
echo  ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo  Setup has not been run yet on THIS folder.
  echo.
  echo  1. Double-click install.bat first
  echo  2. Wait until it says DONE
  echo  3. Then double-click start.bat again
  echo.
  pause
  exit /b 1
)

if not exist "backend\app\main.py" (
  echo  [ERROR] App files are missing from this folder.
  echo  Make sure you extracted the full download, not just one file.
  echo  You should see folders named: backend, frontend, brand
  echo.
  pause
  exit /b 1
)

REM Free port 8787 if a leftover process is stuck
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":8787" ^| findstr "LISTENING"') do (
  echo  Clearing old app still using port 8787...
  taskkill /PID %%P /F >nul 2>&1
)

if exist "data\startup.log" del "data\startup.log" >nul 2>&1
if not exist "data" mkdir "data" >nul 2>&1

echo  Starting the app... please wait.
echo  (A black window may open - that is normal. Leave it alone.)
echo.

REM Start server in its own window that STAYS open so errors are visible
REM /k keeps the window if something fails; uvicorn keeps it open when healthy
start "Household Money - keep open" cmd /k "cd /d ""%~dp0"" && "".venv\Scripts\python.exe"" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787"

REM Wait until the app answers (up to ~45 seconds)
set /a tries=0
:waitloop
set /a tries+=1
if %tries% GTR 45 goto notready

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
echo  Look at the other window titled:
echo    "Household Money - keep open"
echo  and read any red error text there.
echo.
echo  Common fixes:
echo    - Run install.bat again, then start.bat
echo    - Restart the computer and try start.bat
echo    - Make sure nothing else is using the app
echo.
echo  Opening the address anyway so you can retry refresh...
start "" "http://127.0.0.1:8787"
echo.
pause
exit /b 1

:ready
echo  App is ready.
echo  Opening your browser...
echo.
start "" "http://127.0.0.1:8787"

echo  ============================================
echo   Household Money is running
echo  ============================================
echo.
echo  Browser address:  http://127.0.0.1:8787
echo.
echo  First login (until you change it):
echo    Username: admin
echo    Password: admin
echo.
echo  IMPORTANT:
echo    - Keep the other window open while you use the app
echo    - When finished, close the "Household Money - keep open" window
echo.
echo  You can close THIS window now.
echo.
pause
endlocal
