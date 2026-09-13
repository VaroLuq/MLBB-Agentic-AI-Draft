@echo off
REM Double-clickable launcher for the ML Draft Copilot dashboard.
REM %~dp0 = the folder this .bat file lives in, so it works no matter
REM where it's launched from (desktop shortcut, Start Menu, etc.) -
REM no need to "cd" into the project folder first.

cd /d "%~dp0"

set PORT=8501

REM Safeguard: if something is already listening on the dashboard's
REM port, assume it's an already-running instance and open that
REM instead of starting a second one. Streamlit would otherwise just
REM bump to the next free port (8502, 8503, ...) and you'd end up with
REM multiple instances open, each with its own cache/state.
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo ML Draft Copilot already appears to be running on port %PORT%.
    echo Opening it in your browser instead of starting a new instance...
    start http://localhost:%PORT%
    pause
    exit /b
)

echo Starting ML Draft Copilot...
echo (Make sure Ollama is running in the background, or draft
echo  recommendations won't work - see README.md if it's not.)
echo.

venv\Scripts\python.exe -m streamlit run src\ui\app.py

REM Keep the window open if Streamlit exits/crashes immediately,
REM so you can actually read the error instead of it flashing shut.
pause
