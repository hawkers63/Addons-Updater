@echo off
setlocal
set "PYTHON_DIR=%LOCALAPPDATA%\Programs\Python\Python311"
if not exist "%PYTHON_DIR%\python.exe" (
    echo ESO Addons Updater requires Python 3.11 at "%PYTHON_DIR%".
    pause
    exit /b 1
)
"%PYTHON_DIR%\python.exe" -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo Run this command to install CustomTkinter.
    echo "%PYTHON_DIR%\python.exe" -m pip install -r "%~dp0requirements-updater.txt"
    pause
    exit /b 1
)
cd /d "%~dp0"
start "" "%PYTHON_DIR%\pythonw.exe" "%~dp0addons_updater.py"
