# Build installer.exe from installer.cs
# Usage: .\build_installer.ps1

$cs = Join-Path $PSScriptRoot "installer.cs"
$exe = Join-Path $PSScriptRoot "installer.exe"

# Find csc.exe from .NET Framework
$csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework64\*\csc.exe" -ErrorAction SilentlyContinue |
       Sort-Object { [version](Split-Path (Split-Path $_.FullName) -Leaf).TrimStart('v') } -Descending |
       Select-Object -First 1

if (-not $csc) {
    $csc = Get-ChildItem "C:\Windows\Microsoft.NET\Framework\*\csc.exe" -ErrorAction SilentlyContinue |
           Sort-Object { [version](Split-Path (Split-Path $_.FullName) -Leaf).TrimStart('v') } -Descending |
           Select-Object -First 1
}

if (-not $csc) {
    Write-Host "ERROR: csc.exe not found" -ForegroundColor Red
    exit 1
}

Write-Host "Using: $($csc.FullName)" -ForegroundColor Cyan
Write-Host "Compiling..." -ForegroundColor Yellow

# Compile as Windows app (no console window at all)
& $csc.FullName /target:winexe /out:$exe /optimize+ $cs

if (Test-Path $exe) {
    $size = (Get-Item $exe).Length
    Write-Host "Built: $exe ($size bytes)" -ForegroundColor Green
    Write-Host "`nUpload installer.exe to your Cloudflare worker." -ForegroundColor Cyan
    Write-Host "User runs: irm <url>/installer.exe -OutFile i.exe; .\i.exe; del i.exe" -ForegroundColor Cyan
} else {
    Write-Host "Build failed!" -ForegroundColor Red
}
