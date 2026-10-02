@echo off
REM One-time setup on the server: creates a virtual environment and installs dependencies.
REM Requires Python 3.14 on PATH.
cd /d "%~dp0"

python -m venv venv
call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Install complete. Edit start_server.bat (secret key, allowed hosts), then run it.
pause
