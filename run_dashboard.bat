@echo off
REM Double-clickable launcher for the Draft Copilot web app.
REM %~dp0 = the folder this .bat file lives in, so it works no matter
REM where it's launched from (desktop shortcut, Start Menu, etc.) -
REM no need to "cd" into the project folder first.

cd /d "%~dp0"

if not defined DRAFT_COPILOT_PORT set DRAFT_COPILOT_PORT=8600
set PORT=%DRAFT_COPILOT_PORT%

REM Safeguard: if something is already listening on the app's port, assume
REM it's an already-running instance and open that instead of starting a
REM second one (which would fail to bind the port anyway).
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %ERRORLEVEL%==0 (
    echo Draft Copilot already appears to be running on port %PORT%.
    echo Opening it in your browser instead of starting a new instance...
    start http://localhost:%PORT%
    pause
    exit /b
)

echo Starting Draft Copilot...
echo (Recommendations need Ollama running - the header shows its status.)
echo Close this window to stop the app.
echo.

venv\Scripts\python.exe -m src.web.server --open

REM Keep the window open if the server exits/crashes immediately,
REM so you can actually read the error instead of it flashing shut.
pause
