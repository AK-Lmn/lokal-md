@echo off
REM One-time installation. NEEDS INTERNET. Afterwards the app runs fully offline.
cd /d "%~dp0"
python -m venv .venv || (echo Python 3.11+ is required & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
.venv\Scripts\python.exe scripts\prepare_models.py --install-ollama
echo.
echo Setup finished. Disconnect from the internet if you like, then start run.bat.
pause
