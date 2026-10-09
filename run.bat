@echo off
REM Starts Tala on this computer only (127.0.0.1:8501). Works without internet.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
REM Start the local LLM server if Ollama is installed and not running
where ollama >nul 2>nul && (tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || start "" /B ollama serve)
start "" http://127.0.0.1:8501
.venv\Scripts\python.exe -m streamlit run app.py
