@echo off
cd /d "%~dp0"
if not exist ".venv-release\Scripts\python.exe" py -3.11 -m venv .venv-release
if errorlevel 1 goto fail
.venv-release\Scripts\python.exe -m pip install -r requirements-release.txt
if errorlevel 1 goto fail
.venv-release\Scripts\python.exe tools\build_release.py
if errorlevel 1 goto fail
echo.
echo Built EXE in dist and release package in release.
pause
exit /b 0
:fail
echo Release build failed. See README.md for Python 3.11 setup.
pause
exit /b 1
