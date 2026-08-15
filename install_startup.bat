@echo off
setlocal
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PROJECT=C:\Users\ravij\Downloads\OA\CodePilot_GeminiWebAPI_V13"
if not exist "%PROJECT%\run_agent.bat" (
  echo ERROR: Project folder not found:
  echo %PROJECT%
  pause
  exit /b 1
)
copy /Y "%PROJECT%\invisible_agent.vbs" "%STARTUP%\invisible_agent.vbs" >nul
if errorlevel 1 (
  echo ERROR: Could not install startup VBS.
  pause
  exit /b 1
)
echo Startup launcher installed:
echo %STARTUP%\invisible_agent.vbs
echo.
echo It will launch CodePilot invisibly when Windows logs in.
endlocal
