@echo off
REM Pulls the latest version from GitHub and, if anything changed, installs it and restarts the server.
REM Run every few minutes by the "IMS auto update" scheduled task (see DEPLOY.md); safe to run by hand.
REM Progress is written to update.log in this folder.
setlocal
cd /d "%~dp0"
set "LOG=%~dp0update.log"
set BRANCH=main

git fetch --quiet origin %BRANCH% >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] git fetch failed - check the network or GitHub access. >> "%LOG%"
    exit /b 1
)
for /f %%i in ('git rev-parse HEAD') do set LOCAL=%%i
for /f %%i in ('git rev-parse origin/%BRANCH%') do set REMOTE=%%i
if "%LOCAL%"=="%REMOTE%" exit /b 0

echo [%date% %time%] Updating %LOCAL% to %REMOTE% >> "%LOG%"
git pull --ff-only --quiet origin %BRANCH% >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] git pull failed - were files changed on the server? Run "git status" in this folder. >> "%LOG%"
    exit /b 1
)

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else if exist "..\IMS_venv\Scripts\activate.bat" (
    call "..\IMS_venv\Scripts\activate.bat"
)
python -m pip install --quiet -r requirements.txt >> "%LOG%" 2>&1
python manage.py migrate --noinput >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] migrate failed - server not restarted; fix and push again. >> "%LOG%"
    exit /b 1
)

if not exist serve.pid (
    echo [%date% %time%] Updated, but serve.pid is missing - start the server with start_server.bat. >> "%LOG%"
    exit /b 0
)
set /p PID=<serve.pid
REM Only stop it if that pid is still a Python process (serve.pid can be left over after a crash).
tasklist /FI "PID eq %PID%" /FI "IMAGENAME eq python*" | find "%PID%" >nul
if errorlevel 1 (
    echo [%date% %time%] Updated, but the server in serve.pid is not running - start it with start_server.bat. >> "%LOG%"
    exit /b 0
)
REM start_server.bat starts the server again with the new code.
taskkill /PID %PID% /F >> "%LOG%" 2>&1
echo [%date% %time%] Restarted the server (old pid %PID%) >> "%LOG%"
exit /b 0
