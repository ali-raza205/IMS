@echo off
REM Starts the IMS app in production mode with Waitress.
REM Before the first start: run install.bat and create IMS\local_settings.py (see DEPLOY.md).
REM The server restarts by itself whenever it stops, e.g. when update.bat installs a new version.
cd /d "%~dp0"

set DJANGO_DEBUG=False

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else if exist "..\IMS_venv\Scripts\activate.bat" (
    call "..\IMS_venv\Scripts\activate.bat"
)

:run
python manage.py collectstatic --noinput
python serve.py
echo [%date% %time%] Server stopped - restarting in 5 seconds (close this window to stop it for good).
timeout /t 5 /nobreak >nul
goto run
