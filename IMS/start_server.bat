@echo off
REM Starts the IMS app in production mode with Waitress.
REM Run install.bat once before the first start.
cd /d "%~dp0"

set DJANGO_DEBUG=False
REM Set these for your server before going live:
REM set DJANGO_SECRET_KEY=replace-with-a-long-random-string
REM set DJANGO_ALLOWED_HOSTS=192.168.0.44,localhost
REM set WAITRESS_PORT=8000

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else (
    call "..\IMS_venv\Scripts\activate.bat"
)

python manage.py collectstatic --noinput
python serve.py
