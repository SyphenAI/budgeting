@echo off
setlocal EnableExtensions
title Household Money
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Setup has not been run yet.
  echo  Please double-click install.bat first, then try again.
  echo.
  pause
  exit /b 1
)

echo.
echo  Starting Household Money...
echo  Leave this window open while you use the app.
echo  Close this window when you are finished.
echo.

REM Start the app server in the background of this window
start "Household Money server" /min cmd /c "cd /d ""%~dp0"" && "".venv\Scripts\python.exe"" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787"

REM Give the server a moment to boot
timeout /t 3 /nobreak >nul

REM Open the default browser
start "" "http://127.0.0.1:8787"

echo  Browser should open to http://127.0.0.1:8787
echo.
echo  First login (only until you change it):
echo    Username: admin
echo    Password: admin
echo.
echo  Keep the small server window running in the background.
echo  Press any key here to stop the app when you are done.
echo.
pause >nul

REM Stop server processes we started for this app on port 8787
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8787" ^| findstr "LISTENING"') do (
  taskkill /PID %%P /F >nul 2>&1
)

echo  App stopped.
timeout /t 2 >nul
endlocal
