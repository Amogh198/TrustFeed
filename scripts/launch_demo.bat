@echo off
setlocal
set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

where uvicorn >nul 2>nul
if errorlevel 1 (
  echo uvicorn was not found. Create/activate .venv and install backend requirements first.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo npm was not found. Install Node.js before launching the frontend.
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo frontend\node_modules is missing. Run "npm install" from frontend\ first.
  exit /b 1
)

start "TrustFeed API" cmd /k "cd /d ""%ROOT_DIR%"" && uvicorn backend.api.app.main:app --reload --port 8000"

echo.
echo ============================================================
echo   _____              _   _____               _
echo  ^|_   _^|            ^| ^| ^|  ___^|             ^| ^|
echo    ^| ^|_ __ _   _ ___^| ^|_^| ^|__ ___  ___ _ __ ^| ^|
echo    ^| ^| '__^| ^| ^| / __^| __^|  __/ _ \ / _ \ '_ \^| ^|
echo    ^| ^| ^|  ^| |_| \__ \ ^|_^| ^| ^|  __/  __/ ^| ^| ^|_
echo    \_/_^|   \__,_^|___/\__\_^|  \___^|\___^|_^| ^|_(_)
echo.
echo           TrustFeed Demo Environment Live
echo ============================================================
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8000
echo API docs: http://localhost:8000/docs
echo.
cd /d "%ROOT_DIR%\frontend"
npm run dev -- --host 127.0.0.1
endlocal
