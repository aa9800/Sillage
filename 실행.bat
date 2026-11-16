@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [Sillage] Python 3.10+ is required. Install it from https://www.python.org/downloads/ and run again.
  pause
  exit /b 1
)
if not exist "dist\index.html" (
  echo [Sillage] dist folder is missing. Run "npm ci" and "npm run build" first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [Sillage] First run: creating virtual environment and installing packages...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
)
echo [Sillage] Starting server at http://127.0.0.1:8765  (close this window to stop)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8765
pause
