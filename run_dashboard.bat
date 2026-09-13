@echo off
REM Double-clickable launcher for the ML Draft Copilot dashboard.
REM %~dp0 = the folder this .bat file lives in, so it works no matter
REM where it's launched from (desktop shortcut, Start Menu, etc.) -
REM no need to "cd" into the project folder first.

cd /d "%~dp0"

echo Starting ML Draft Copilot...
echo (Make sure Ollama is running in the background, or draft
echo  recommendations won't work - see README.md if it's not.)
echo.

venv\Scripts\python.exe -m streamlit run src\ui\app.py

REM Keep the window open if Streamlit exits/crashes immediately,
REM so you can actually read the error instead of it flashing shut.
pause
