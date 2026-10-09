@echo off
REM Copies new and changed transaction pictures and receipts to MEDIA_BACKUP_DIR (set in IMS\local_settings.py).
REM Run daily by the "IMS media backup" scheduled task (see DEPLOY.md); safe to run by hand.
REM Progress is written to backup_media.log in this folder.
setlocal
cd /d "%~dp0"
set "LOG=%~dp0backup_media.log"

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else if exist "..\IMS_venv\Scripts\activate.bat" (
    call "..\IMS_venv\Scripts\activate.bat"
)

python manage.py backup_media >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Media backup FAILED - see the lines above. >> "%LOG%"
    exit /b 1
)
exit /b 0
