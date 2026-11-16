@echo off
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [Sillage] Python 3.10+ is required. Install it from https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^) and run again.
  pause
  exit /b 1
)
if not exist "dist\index.html" (
  echo [Sillage] dist folder is missing. Run "npm ci" and "npm run build" first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [Sillage] First run: creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [Sillage] Could not create the virtual environment.
    pause
    exit /b 1
  )
)
rem Install packages if any are missing (also recovers from an interrupted first install)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, dotenv, pydantic, mcp" >nul 2>nul
if errorlevel 1 (
  echo [Sillage] Installing packages ^(1-2 minutes, internet needed^)...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo [Sillage] Package install failed. Check the internet connection and run again.
    pause
    exit /b 1
  )
)
echo [Sillage] Starting server at http://127.0.0.1:8765  (close this window to stop)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8765
pause
