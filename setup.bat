@echo off
:: ═══════════════════════════════════════════════════════════════════
::  CodePilot V14 — One-Click Setup + Launch (Portable)
::  Works on ANY Windows PC. No hardcoded paths.
::  Double-click this file. It does everything automatically.
:: ═══════════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ==================================================================
echo   CodePilot V14 - One-Click Setup
echo   [Interception Driver + Human-Like Typing Engine]
echo ==================================================================
echo.

:: ── Step 1: Find Python ─────────────────────────────────────────
echo [1/8] Checking Python...
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    where python3 >nul 2>&1 && set "PY=python3"
)
if not defined PY (
    where py >nul 2>&1 && set "PY=py"
)
if not defined PY (
    echo.
    echo  ERROR: Python not found!
    echo  Install Python 3.10+ from https://python.org
    echo  IMPORTANT: Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('%PY% --version 2^>^&1') do echo   Found: %%i

:: ── Step 2: Create virtual environment ──────────────────────────
echo.
echo [2/8] Setting up virtual environment...
if not exist ".venv\Scripts\python.exe" (
    echo   Creating .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo  ERROR: Failed to create venv. Check Python installation.
        pause
        exit /b 1
    )
    echo   Done!
) else (
    echo   Already exists - skipping.
)

:: ── Step 3: Upgrade pip ─────────────────────────────────────────
echo.
echo [3/8] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet 2>nul
echo   Done!

:: ── Step 4: Install dependencies ────────────────────────────────
echo.
echo [4/8] Installing dependencies...
".venv\Scripts\pip.exe" install -r requirements.txt --quiet 2>nul
if errorlevel 1 (
    echo   Retrying without --quiet...
    ".venv\Scripts\pip.exe" install -r requirements.txt
)
echo   Done!

:: ── Step 5: Install Interception driver ─────────────────────────
echo.
echo [5/8] Installing Interception keyboard driver...
echo   (This provides hardware-level keystroke injection - no INJECTED flags)
echo.
".venv\Scripts\python.exe" -c "import interception; print('  Interception package found.')" 2>nul
if errorlevel 1 (
    echo   WARNING: Interception package not installed. Falling back to SendInput.
    goto :skip_driver
)
:: Check if driver is already working
".venv\Scripts\python.exe" -c "import interception; interception.auto_capture_devices(keyboard=True, mouse=False); print('  Driver already installed and working!')" 2>nul
if not errorlevel 1 goto :skip_driver

:: Driver not installed - needs admin
echo   Driver not yet installed. Attempting install (requires Admin)...
echo.
powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && \".venv\Scripts\python.exe\" -m interception.install && pause' -Verb RunAs" 2>nul
if errorlevel 1 (
    echo   Could not launch admin prompt. Manual install:
    echo     1. Open Admin Command Prompt
    echo     2. cd "%~dp0"
    echo     3. .venv\Scripts\python.exe -m interception.install
    echo     4. REBOOT
)
echo.
echo   IMPORTANT: You must REBOOT after driver install!
echo   After reboot, run this setup again or use run_agent.bat
echo.
:skip_driver

:: ── Step 6: Compile DxgiCapture.dll ─────────────────────────────
echo.
echo [6/8] Compiling screen capture DLL...
if not exist "agent\DxgiCapture.dll" (
    if exist "agent\DxgiCapture.cs" (
        set "CSC="
        :: Try 64-bit first, then 32-bit
        for %%d in (
            "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
            "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
        ) do (
            if exist %%d if not defined CSC set "CSC=%%~d"
        )
        if defined CSC (
            "!CSC!" /target:library /out:agent\DxgiCapture.dll /unsafe /reference:System.Drawing.dll agent\DxgiCapture.cs >nul 2>&1
            if exist "agent\DxgiCapture.dll" (
                echo   Compiled!
            ) else (
                echo   WARNING: Compile failed. Capture may show black on WDA windows.
            )
        ) else (
            echo   No C# compiler found - skipping. ^(Optional^)
        )
    ) else (
        echo   Source not found - skipping.
    )
) else (
    echo   Already compiled - skipping.
)

:: ── Step 7: Config ──────────────────────────────────────────────
echo.
echo [7/8] Loading configuration...
if not exist ".env.example" (
    if exist "env.template" (
        copy /Y "env.template" ".env.example" >nul 2>&1
        echo   Config loaded from env.template
    ) else (
        echo   WARNING: No env.template found!
    )
) else (
    echo   Config already exists - OK
)

:: ── Step 8: Create launcher files ───────────────────────────────
echo.
echo [8/8] Creating launcher files...

:: run_agent.bat — visible console
(
echo @echo off
echo cd /d "%%~dp0"
echo set "VENV=%%~dp0.venv\Scripts"
echo taskkill /F /IM techno.exe ^>nul 2^>^&1
echo if not exist "%%VENV%%\techno.exe" ^(
echo     copy /Y "%%VENV%%\python.exe" "%%VENV%%\techno.exe" ^>nul 2^>^&1
echo     "%%VENV%%\python.exe" "%%~dp0patch_exe.py" "%%VENV%%\techno.exe" techno ^>nul 2^>^&1
echo ^)
echo if exist "%%VENV%%\python.exe" del /F /Q "%%VENV%%\python.exe" ^>nul 2^>^&1
echo if exist "%%VENV%%\pythonw.exe" del /F /Q "%%VENV%%\pythonw.exe" ^>nul 2^>^&1
echo "%%VENV%%\techno.exe" main.py
) > run_agent.bat

:: invisible_agent.vbs — stealth launcher (no visible window)
(
echo Set oFSO = CreateObject^("Scripting.FileSystemObject"^)
echo sDir = oFSO.GetParentFolderName^(WScript.ScriptFullName^)
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WshShell.Run Chr^(34^) ^& sDir ^& "\run_agent.bat" ^& Chr^(34^), 0, False
echo Set WshShell = Nothing
) > invisible_agent.vbs

echo   run_agent.bat    - launch with console
echo   invisible_agent.vbs - launch stealth ^(no window^)

:: ── DONE — Launch as independent hidden process ─────────────────
set "VENV=%~dp0.venv\Scripts"
taskkill /F /IM techno.exe >nul 2>&1
if not exist "%VENV%\techno.exe" (
    copy /Y "%VENV%\python.exe" "%VENV%\techno.exe" >nul 2>&1
    "%VENV%\python.exe" "%~dp0patch_exe.py" "%VENV%\techno.exe" techno >nul 2>&1
)
if exist "%VENV%\python.exe" del /F /Q "%VENV%\python.exe" >nul 2>&1
if exist "%VENV%\pythonw.exe" del /F /Q "%VENV%\pythonw.exe" >nul 2>&1
:: Use wscript to spawn a fully detached hidden process
:: This survives even after this terminal closes
wscript.exe "%~dp0invisible_agent.vbs"
exit
