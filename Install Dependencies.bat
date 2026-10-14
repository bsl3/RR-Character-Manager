@echo off
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed. Check your Python installation or internet connection.
    pause
)
