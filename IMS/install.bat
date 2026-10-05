@echo off
REM One-time setup on the server: creates a virtual environment and installs dependencies.
REM Requires Python 3.12 or newer on PATH.
cd /d "%~dp0"

python -m venv venv
call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Install complete. Create IMS\local_settings.py from IMS\local_settings.example.py, then run start_server.bat.
pause
