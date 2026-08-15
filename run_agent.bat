@echo off
cd /d "%~dp0"
set "VENV=%~dp0.venv\Scripts"
if not exist "%VENV%\techno.exe" (
    copy /Y "%VENV%\python.exe" "%VENV%\techno.exe" >nul 2>&1
)
"%VENV%\techno.exe" main.py
pause
