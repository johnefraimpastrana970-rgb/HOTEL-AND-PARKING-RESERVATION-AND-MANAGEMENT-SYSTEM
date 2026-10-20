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
start "Central Channel backend" /D "%BACKEND_DIR%" "%PYTHON%" run.py

echo Waiting for the local backend...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(60); do { try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if ($response.StatusCode -eq 200) { exit 0 } } catch { }; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo The backend did not become ready. Check its console for database configuration or connection errors.
    pause
    exit /b 1
)

echo Opening the NEXORA landing page...
start "" "%SITE_URL%"
exit /b 0
