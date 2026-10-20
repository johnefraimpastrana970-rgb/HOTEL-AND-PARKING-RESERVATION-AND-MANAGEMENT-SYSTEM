@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\bin\python.exe"
set "BACKEND_DIR=%ROOT%CENTRAL CHANNEL"
set "SITE_URL=http://127.0.0.1:8000/LOGIN%%20PANEL/landing.html"

if not exist "%PYTHON%" (
    echo Python environment not found: "%PYTHON%"
    echo Create or restore the workspace .venv, then try again.
    pause
    exit /b 1
)

if not exist "%BACKEND_DIR%\run.py" (
    echo Backend entry point not found: "%BACKEND_DIR%\run.py"
    pause
    exit /b 1
)

echo Starting Central Channel. Keep its console window open while using the site.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$live = $false; try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health/live' -TimeoutSec 3; $live = $response.StatusCode -eq 200 } catch { }; if ($live) { Write-Output 'A Central Channel API is already running; reusing it.'; exit 0 }; $client = New-Object System.Net.Sockets.TcpClient; $portOccupied = $false; try { try { $client.Connect('127.0.0.1', 8000); $portOccupied = $true } catch [System.Net.Sockets.SocketException] { } } finally { $client.Dispose() }; if ($portOccupied) { $listener = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1; $owner = if ($listener) { $listener.OwningProcess } else { 'unknown' }; $name = if ($listener) { (Get-Process -Id $owner -ErrorAction SilentlyContinue).ProcessName } else { 'unknown process' }; Write-Error ('Port 8000 is occupied by ' + $name + ' (PID ' + $owner + ').'); exit 2 }; try { Start-Process -FilePath '%PYTHON%' -ArgumentList '-u', 'run.py' -WorkingDirectory '%BACKEND_DIR%' -ErrorAction Stop | Out-Null } catch { Write-Error ('Could not start the Python backend: ' + $_.Exception.Message); exit 1 }; exit 0"
if errorlevel 2 (
    echo Port 8000 is already in use by a service that is not the reservation API.
    echo Close that service before starting Central Channel.
    pause
    exit /b 2
)
if errorlevel 1 (
    echo Could not start the Central Channel backend.
    pause
    exit /b 1
)

echo Waiting for the local backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(60); do { try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health/ready' -TimeoutSec 3; if ($response.StatusCode -eq 200) { exit 0 } } catch { }; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); try { $live = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health/live' -TimeoutSec 3; if ($live.StatusCode -eq 200) { Write-Error 'The API process started, but readiness failed. Check Supabase database and Redis settings in CENTRAL CHANNEL\.env and the backend console.' } } catch { Write-Error 'The API did not become available. Check the backend console for startup errors.' }; exit 1"
if errorlevel 1 (
    echo The backend did not become ready. Check its console and CENTRAL CHANNEL\.env.
    pause
    exit /b 1
)

echo Opening the NEXORA landing page...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath '%SITE_URL%' -ErrorAction Stop | Out-Null } catch { Write-Error ('Could not open the landing page: ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
    echo The backend is ready, but Windows could not open the landing page automatically.
    echo Open this URL manually: %SITE_URL%
    pause
    exit /b 1
)
echo The backend will keep running in its console window. Press Ctrl+C there to stop it.
exit /b 0
