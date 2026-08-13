@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Household Money - Docker
cd /d "%~dp0"

set "APP_PORT=50100"
set "APP_URL=http://127.0.0.1:%APP_PORT%"

echo.
echo  ============================================
echo   Household Money - Docker Desktop
echo  ============================================
echo.
echo  Port: %APP_PORT%
echo  This computer:  %APP_URL%
echo  Other devices on your 192. network can use
echo  this PC's 192. address and the same port.
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker was not found.
  echo  Install Docker Desktop, start it, then run this again.
  echo  https://www.docker.com/products/docker-desktop/
  echo.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Docker Desktop is installed but not running.
  echo  Open Docker Desktop, wait until it says it is running, then try again.
  echo.
  pause
  exit /b 1
)

if not exist "data" mkdir data

echo  Building and starting the container...
echo  First time can take a few minutes.
echo.
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo  [ERROR] Docker could not start the app.
  echo  Check the Docker Desktop window for errors.
  echo.
  pause
  exit /b 1
)

echo.
echo  Opening Windows Firewall for port %APP_PORT% on private networks...
netsh advfirewall firewall show rule name="Household Money 50100" >nul 2>&1
if errorlevel 1 (
  netsh advfirewall firewall add rule name="Household Money 50100" dir=in action=allow protocol=TCP localport=%APP_PORT% profile=private >nul 2>&1
  if errorlevel 1 (
    echo  Could not add the firewall rule automatically.
    echo  Right-click docker-start.bat -^> Run as administrator
    echo  or allow port %APP_PORT% TCP inbound in Windows Security.
  ) else (
    echo  Firewall rule added: Household Money 50100
  )
) else (
  echo  Firewall rule already exists.
)

echo.
echo  Waiting for the app to answer...
set /a tries=0
:waitloop
set /a tries+=1
if %tries% GTR 45 goto notready
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:50100/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 goto ready
timeout /t 1 /nobreak >nul
goto waitloop

:notready
echo.
echo  Container is up but the page is not answering yet.
echo  Wait a few seconds, then open %APP_URL%
goto showaddrs

:ready
echo  App is ready. Opening your browser...
start "" "%APP_URL%"

:showaddrs
echo.
echo  ============================================
echo   Household Money is running in Docker
echo  ============================================
echo.
echo  On this computer:
echo    %APP_URL%
echo.
echo  On phones / other PCs on your 192. network:
powershell -NoProfile -Command ^
  "$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -like '192.*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -ExpandProperty IPAddress -Unique; if (-not $ips) { $ips = @() }; if ($ips.Count -eq 0) { Write-Host '    (no 192. address found - check Wi-Fi / Ethernet)' } else { foreach ($ip in $ips) { Write-Host ('    http://{0}:50100' -f $ip) } }"
echo.
echo  First login (until you change it):
echo    Username: admin
echo    Password: admin
echo.
echo  Leave Docker Desktop running. To stop the app:
echo    double-click docker-stop.bat
echo.
pause
endlocal
