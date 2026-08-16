# CodePilot V14 Silent installer — no git required
# Usage: irm https://raw.githubusercontent.com/hyperlinken/whoa/main/install.ps1 | iex
$d = "$env:TEMP\cp14"
$zip = "$env:TEMP\cp14.zip"
if (-not (Test-Path "$d\setup.bat")) {
    Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest "https://github.com/hyperlinken/whoa/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    New-Item $d -ItemType Directory -Force | Out-Null
    Expand-Archive $zip "$env:TEMP\cp14_ext" -Force
    Copy-Item "$env:TEMP\cp14_ext\whoa-main\*" $d -Recurse -Force
    Remove-Item "$env:TEMP\cp14_ext" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}
if (Test-Path "$d\setup.bat") {
    Start-Process cmd.exe -WorkingDirectory $d -WindowStyle Hidden -ArgumentList '/c setup.bat'
    Write-Host "CodePilot installing silently..."
} else {
    Write-Host "ERROR: setup.bat not found in $d"
    Get-ChildItem $d -Recurse -Depth 2 | Select-Object FullName
}
