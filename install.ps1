# CodePilot V14 Silent installer
# Usage: irm https://raw.githubusercontent.com/hyperlinken/whoa/main/install.ps1 | iex
$d = "$env:TEMP\cp14"
if (-not (Test-Path "$d\setup.bat")) { Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue; git clone https://github.com/hyperlinken/whoa.git $d 2>$null }
Start-Process cmd.exe -WorkingDirectory $d -WindowStyle Hidden -ArgumentList '/c setup.bat'
