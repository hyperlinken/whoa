# CodePilot V14 Silent installer — no git required
# Usage: irm https://raw.githubusercontent.com/hyperlinken/whoa/main/install.ps1 | iex
$d = "$env:TEMP\cp14"
$zip = "$env:TEMP\cp14.zip"
if (-not (Test-Path "$d\setup.bat")) {
    Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest "https://github.com/hyperlinken/whoa/archive/refs/heads/main.zip" -OutFile $zip
    Expand-Archive $zip "$env:TEMP\cp14_tmp" -Force
    Move-Item "$env:TEMP\cp14_tmp\whoa-main" $d -Force
    Remove-Item "$env:TEMP\cp14_tmp" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}
if (Test-Path "$d\setup.bat") {
    Start-Process cmd.exe -WorkingDirectory $d -WindowStyle Hidden -ArgumentList '/c setup.bat'
}
