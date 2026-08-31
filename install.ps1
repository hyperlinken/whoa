# CodePilot V14 — One-Line Install + Stealth Launch (Zero Input)
# Usage: powershell -c "irm https://raw.githubusercontent.com/hyperlinken/whoa/more/install.ps1 | iex"
# ------------------------------------------------------------
# Detach from the PowerShell window used to launch the installer
# ------------------------------------------------------------
if (-not $env:TECHNO_INSTALLER_CHILD) {
    $env:TECHNO_INSTALLER_CHILD = '1'

    $scriptUrl = 'https://raw.githubusercontent.com/hyperlinken/whoa/more/install.ps1'

    Start-Process powershell.exe `
        -WindowStyle Hidden `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"& { irm '$scriptUrl' | iex }`""

    exit
}

$ErrorActionPreference = 'Stop'
$repo = 'hyperlinken/whoa'
$branch = 'more'
$dir  = "$env:LOCALAPPDATA\techno"

Write-Host "`n===== CodePilot V14 — Installing... =====" -ForegroundColor Cyan

# -- Post-reboot resume --
$resumeFlag = Join-Path $dir ".resume_after_reboot"
if (Test-Path $resumeFlag) {
    Write-Host "[RESUME] Post-reboot launch..." -ForegroundColor Green
    Remove-Item $resumeFlag -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "TechnoResume" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
    $vbs = Join-Path $dir "stealth.vbs"
    if (Test-Path $vbs) {
        & wscript.exe $vbs
        Write-Host "Running! NumLock ON = hotkeys | ESC = stop" -ForegroundColor Green
    }
    exit 0
}

# 1. Kill old
Get-Process -Name techno -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# 2. Download
Write-Host "[1/6] Downloading from $repo ($branch)..." -ForegroundColor Yellow
$zip = "$env:TEMP\t_$(Get-Random).zip"
try {
    Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/$branch.zip" -OutFile $zip -UseBasicParsing
} catch {
    Write-Host "  Trying alternative URL..." -ForegroundColor Yellow
    Invoke-WebRequest "https://github.com/$repo/archive/$branch.zip" -OutFile $zip -UseBasicParsing
}
if (-not (Test-Path $zip)) { Write-Host "Download failed!" -ForegroundColor Red; exit 1 }

# 3. Extract
Write-Host "[2/6] Extracting..." -ForegroundColor Yellow
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
$tmp = "$env:TEMP\t_ex_$(Get-Random)"
Expand-Archive $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
Move-Item $inner.FullName $dir -Force
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue

# 4. Python + venv + deps
Write-Host "[3/6] Setting up Python..." -ForegroundColor Yellow
$py = $null
foreach ($c in @('python','python3','py')) {
    try { $v = & $c --version 2>&1; if ($LASTEXITCODE -eq 0) { $py = $c; Write-Host "  Found: $v"; break } } catch {}
}
if (-not $py) { Write-Host "ERROR: Python not found! Install from python.org" -ForegroundColor Red; exit 1 }

$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    & $py -m venv (Join-Path $dir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Host "venv failed!" -ForegroundColor Red; exit 1 }
}
& $vpy -m pip install --upgrade pip -q 2>$null
& $vpy -m pip install -r (Join-Path $dir "requirements.txt") -q 2>$null
& $vpy -m pip install -e $dir -q 2>$null
Write-Host "  Done!" -ForegroundColor Green

# 5. Config
Write-Host "[4/6] Configuring..." -ForegroundColor Yellow
$envFile = Join-Path $dir ".env.example"
$cfgBlob = "IyBDb2RlUGlsb3QgVjE0IENvbmZpZ3VyYXRpb24KR0VNSU5JX0FQSV9LRVlfRU5DPVFWRXVRV0k0VWs0MlRGTnZjVTFQYUhoUFQwWmxZbGRNTlcxeVQybGZVa2QwVG5OSGEyVldja2xKUWxOdk4yd3RjRE01Y1djPQpHRU1JTklfMVBTSUQ9Zy5hMDAwQndsSmRTTXFuNVJ3QUcyOU5vRVN5bEZpMFBRN3ZBcDl2T3FhSVhQY2Y2bFhDV0I2SkdGT243ZFEwR3N6R0ExZ1Y5VElfUUFDZ1lLQVI0U0FSTVNGUUhHWDJNaUZNNzFNSjE3ckpTWGxGeDRsSmNZM2hvVkFVRjh5S3JxNmJzckNIR0szVmhncEZQVVItcmEwMDc2CkdFTUlOSV8xUFNJRFRTPXNpZHRzLUNqWUJYTXc0MVRIdkRXUWNBNHpGeEVlaUNqWVV1TXNOSVVPb1RzSFN0X2lhLVp6RG9RaE1vYlgxVElIRXpKWXU5ZXcxUjc1aDFDc1FBQQpHRU1JTklfTU9ERUw9cHJvX2ZpcnN0CkdFTUlOSV9NQVhfQVRURU1QVFM9NQpHRU1JTklfTU9ERUxfVFJJRVM9MwpHRU1JTklfVElNRU9VVD0xODAKR0VNSU5JX0FUVEVNUFRfVElNRU9VVD0xODAKR0VNSU5JX0lOSVRfVElNRU9VVD0zMApHRU1JTklfUkVJTklUX1BBVVNFPTEKR0VNSU5JX01BWF9CQUNLT0ZGPTEwCkdFTUlOSV9XQVRDSERPR19USU1FT1VUPTE4MApXUE09MjAwClRZUEVfSU5URVJWQUw9MC4wMTUKRklYX0FVVE9fQ0xPU0U9dHJ1ZQpSRVNVTFRfREVMQVk9MTAKQ0hVTktfQU1PVU5UPTEKQ0hVTktfVFlQRT1jaGFycwpIVFRQX1BST1hZPQpIVFRQU19QUk9YWT0="
$envContent = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($cfgBlob))
[System.IO.File]::WriteAllText($envFile, $envContent)
Write-Host "  Config ready!" -ForegroundColor Green

# 6. Stealth launcher + driver
Write-Host "[5/6] Creating launcher..." -ForegroundColor Yellow
$sd = Join-Path $dir ".venv\Scripts"
$techno = Join-Path $sd "techno.exe"
if (-not (Test-Path $techno)) {
    Copy-Item (Join-Path $sd "python.exe") $techno -Force
    & (Join-Path $sd "python.exe") (Join-Path $dir "patch_exe.py") $techno 2>$null
}
Remove-Item (Join-Path $sd "python.exe") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $sd "pythonw.exe") -Force -ErrorAction SilentlyContinue

$vbs = Join-Path $dir "stealth.vbs"
$vbsContent = @"
Set o = CreateObject("Scripting.FileSystemObject")
d = o.GetParentFolderName(WScript.ScriptFullName)
Set s = CreateObject("WScript.Shell")
s.CurrentDirectory = d
s.Run Chr(34) & d & "\.venv\Scripts\techno.exe" & Chr(34) & " " & Chr(34) & d & "\main.py" & Chr(34), 0, False
"@
[System.IO.File]::WriteAllText($vbs, $vbsContent)

# Try Interception driver (optional)
Write-Host "[6/6] Checking driver..." -ForegroundColor Yellow
$vpy = $techno
$needsReboot = $false
try {
    $chk = & $vpy -c "import interception; interception.auto_capture_devices(keyboard=True, mouse=False); print('OK')" 2>&1
    if ("$chk" -match "OK") {
        Write-Host "  Driver OK!" -ForegroundColor Green
    } else { throw "need" }
} catch {
    Write-Host "  Installing driver (needs Admin)..." -ForegroundColor Yellow
    $drvScript = Join-Path $env:TEMP "t_drv_$(Get-Random).ps1"
    "`$vpy = '$vpy'; & `$vpy -m interception.install" | Set-Content $drvScript -Encoding UTF8
    try {
        Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$drvScript`"" -Verb RunAs -Wait
        $needsReboot = $true
    } catch {
        Write-Host "  Skipped (no admin). Using SendInput fallback." -ForegroundColor Yellow
    }
}

if ($needsReboot) {
    [System.IO.File]::WriteAllText((Join-Path $dir ".resume_after_reboot"), "1")
    $localScript = Join-Path $dir "_resume.ps1"
    @"
`$dir = '$dir'
Remove-Item (Join-Path `$dir '.resume_after_reboot') -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 12
`$vbs = Join-Path `$dir 'stealth.vbs'
if (Test-Path `$vbs) { & wscript.exe `$vbs }
"@ | Set-Content $localScript -Encoding UTF8

    $resumeCmd = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$localScript`""
    New-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "TechnoResume" -Value $resumeCmd -PropertyType String -Force | Out-Null

    $startupDir = [Environment]::GetFolderPath('Startup')
    $startupVbs = Join-Path $startupDir "techno_start.vbs"
    @"
Set s = CreateObject("WScript.Shell")
s.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$localScript""", 0, False
"@ | Out-File $startupVbs -Encoding ASCII

    Write-Host "`n===== RESTARTING IN 10 SECONDS =====" -ForegroundColor Red
    Write-Host "  Auto-launches after restart. Ctrl+C to cancel.`n" -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    Restart-Computer -Force
} else {
    Write-Host "`n===== INSTALLED + RUNNING =====" -ForegroundColor Green
    Write-Host "  Location : $dir" -ForegroundColor DarkGray
    Write-Host "  Process  : techno.exe (hidden)" -ForegroundColor DarkGray
    Write-Host "  NumLock ON = hotkeys | OFF = typing | ESC = stop`n" -ForegroundColor Cyan
    & wscript.exe $vbs
}
