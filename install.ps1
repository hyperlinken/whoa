# CodePilot V14 Silent installer
# Usage: irm https://raw.githubusercontent.com/hyperlinken/whoa/main/install.ps1 | iex
$d = "$env:TEMP\cp14"
# Check git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git not found. Installing..."
    winget install --id Git.Git -e --silent 2>$null
    $env:PATH += ";C:\Program Files\Git\cmd"
}
# Clone
if (-not (Test-Path "$d\setup.bat")) {
    Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
    git clone https://github.com/hyperlinken/whoa.git $d 2>$null
}
# Verify and launch
if (Test-Path "$d\setup.bat") {
    Start-Process cmd.exe -WorkingDirectory $d -WindowStyle Hidden -ArgumentList '/c setup.bat'
} else {
    Write-Host "Clone failed. Run: git clone https://github.com/hyperlinken/whoa.git $d"
}
