# CodePilot V14 — One-Line Install + Stealth Launch
# Usage: powershell -c "irm https://raw.githubusercontent.com/YOURUSER/YOURREPO/main/install.ps1 | iex"
$ErrorActionPreference = 'Stop'
$repo = 'hyperlinken/whoa'
$dir  = "$env:LOCALAPPDATA\techno"

Write-Host "`n===== CodePilot V14 — Installing... =====" -ForegroundColor Cyan

# -- Check if this is a post-reboot resume --
$resumeFlag = Join-Path $dir ".resume_after_reboot"
if (Test-Path $resumeFlag) {
    Write-Host "[RESUME] Post-reboot launch..." -ForegroundColor Green
    Remove-Item $resumeFlag -Force -ErrorAction SilentlyContinue
    # Remove RunOnce registry entry (cleanup)
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "CodePilotResume" -ErrorAction SilentlyContinue
    # Launch stealth
    $vbs = Join-Path $dir "stealth.vbs"
    if (Test-Path $vbs) {
        Start-Sleep -Seconds 5  # wait for desktop to settle
        & wscript.exe $vbs
        Write-Host "Launched! NumLock ON = hotkeys, ESC = stop" -ForegroundColor Green
    } else {
        Write-Host "ERROR: stealth.vbs not found. Run install again." -ForegroundColor Red
    }
    exit 0
}

# 1. Kill old instance
Get-Process -Name techno -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300

# 2. Download
Write-Host "[1/7] Downloading..." -ForegroundColor Yellow
$zip = "$env:TEMP\cp_$(Get-Random).zip"
Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
if (-not (Test-Path $zip)) { Write-Host "Download failed!" -ForegroundColor Red; exit 1 }

# 3. Extract
Write-Host "[2/7] Extracting..." -ForegroundColor Yellow
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
$tmp = "$env:TEMP\cp_ex_$(Get-Random)"
Expand-Archive $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
Move-Item $inner.FullName $dir -Force
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue

# 4. Find Python
Write-Host "[3/7] Checking Python..." -ForegroundColor Yellow
$py = $null
foreach ($c in @('python','python3','py')) {
    try { $v = & $c --version 2>&1; if ($LASTEXITCODE -eq 0) { $py = $c; Write-Host "  $v"; break } } catch {}
}
if (-not $py) { Write-Host "ERROR: Python not found! Install from python.org" -ForegroundColor Red; exit 1 }

# 5. Venv + deps
Write-Host "[4/7] Installing dependencies..." -ForegroundColor Yellow
$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    & $py -m venv (Join-Path $dir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Host "venv failed!" -ForegroundColor Red; exit 1 }
}
& $vpy -m pip install --upgrade pip -q 2>$null
& $vpy -m pip install -r (Join-Path $dir "requirements.txt") -q 2>$null
Write-Host "  Done!" -ForegroundColor Green

# 6. Config
Write-Host "[5/7] Configuring..." -ForegroundColor Yellow
$env_f = Join-Path $dir ".env.example"
$tmpl  = Join-Path $dir "env.template"
if (-not (Test-Path $env_f) -and (Test-Path $tmpl)) { Copy-Item $tmpl $env_f }

# 7. Stealth launcher setup
Write-Host "[6/7] Creating stealth launcher..." -ForegroundColor Yellow
$sd = Join-Path $dir ".venv\Scripts"
$techno = Join-Path $sd "techno.exe"
if (-not (Test-Path $techno)) { Copy-Item (Join-Path $sd "python.exe") $techno -Force }

$vbs = Join-Path $dir "stealth.vbs"
$vbsContent = @"
Set o = CreateObject("Scripting.FileSystemObject")
d = o.GetParentFolderName(WScript.ScriptFullName)
Set s = CreateObject("WScript.Shell")
s.CurrentDirectory = d
s.Run Chr(34) & d & "\.venv\Scripts\techno.exe" & Chr(34) & " " & Chr(34) & d & "\main.py" & Chr(34), 0, False
"@
[System.IO.File]::WriteAllText($vbs, $vbsContent)

# 8. Interception driver
Write-Host "[7/7] Checking Interception driver..." -ForegroundColor Yellow
$needsReboot = $false
try {
    $driverCheck = & $vpy -c "import interception; interception.auto_capture_devices(keyboard=True, mouse=False); print('OK')" 2>&1
    if ($driverCheck -match "OK") {
        Write-Host "  Driver already installed!" -ForegroundColor Green
    } else {
        throw "not working"
    }
} catch {
    Write-Host "  Driver not installed. Installing (needs Admin)..." -ForegroundColor Yellow
    
    # Create an admin install script
    $adminScript = Join-Path $env:TEMP "cp_driver_install.ps1"
    @"
`$vpy = '$vpy'
& `$vpy -m interception.install
"@ | Set-Content $adminScript -Encoding UTF8

    try {
        Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$adminScript`"" -Verb RunAs -Wait
        $needsReboot = $true
        Write-Host "  Driver installed! Reboot required." -ForegroundColor Yellow
    } catch {
        Write-Host "  WARNING: Could not install driver (no admin). Using SendInput fallback." -ForegroundColor Yellow
        Write-Host "  To install later: run as admin: $vpy -m interception.install" -ForegroundColor Yellow
    }
}

if ($needsReboot) {
    # Set resume flag so we auto-launch after reboot
    [System.IO.File]::WriteAllText((Join-Path $dir ".resume_after_reboot"), "1")
    
    # Save this script locally for post-reboot resume
    $localInstall = Join-Path $dir "install.ps1"
    if (-not (Test-Path $localInstall)) {
        # Copy from the downloaded repo
        $srcInstall = Join-Path $dir "install.ps1"
        # It should already be there from the download
    }
    
    # Register RunOnce to auto-launch after reboot
    $resumeCmd = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$localInstall`""
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "CodePilotResume" -Value $resumeCmd
    
    Write-Host "`n===== REBOOTING IN 10 SECONDS =====" -ForegroundColor Red
    Write-Host "  After reboot, CodePilot will auto-launch in background." -ForegroundColor Cyan
    Write-Host "  Press Ctrl+C to cancel reboot.`n" -ForegroundColor Yellow
    
    Start-Sleep -Seconds 10
    Restart-Computer -Force
} else {
    # No reboot needed — launch now
    Write-Host "`n===== INSTALLED + RUNNING =====" -ForegroundColor Green
    Write-Host "  Location : $dir" -ForegroundColor Green
    Write-Host "  Process  : techno.exe (hidden)" -ForegroundColor Green
    Write-Host "  NumLock ON = hotkeys | OFF = typing" -ForegroundColor Cyan
    Write-Host "  ESC = stop`n" -ForegroundColor Cyan
    
    & wscript.exe $vbs
}
