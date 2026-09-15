@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   PFIM - Start application
echo ==========================================
echo.

if not exist "backend\venv\Scripts\activate.bat" (
    echo [ERROR] Backend virtual environment not found in backend\venv
    echo Run setup first: see README.md, section "Quick Start"
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [ERROR] Frontend dependencies are not installed in frontend\node_modules
    echo First run the reproducible setup: scripts\setup.ps1
    pause
    exit /b 1
)

echo Starting backend (http://localhost:8000)...
start "PFIM Backend" cmd /k "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo Starting frontend (http://localhost:5173)...
start "PFIM Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Waiting for the servers to be ready...
ping -n 7 127.0.0.1 >nul

start "" "http://localhost:5173"

echo.
echo Done. Two windows remain open (backend/frontend): close them to stop the app.
endlocal
