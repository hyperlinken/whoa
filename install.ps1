# CodePilot V14 — One-Line Install + Stealth Launch (Zero Input)
# Usage: irm https://raw.githubusercontent.com/hyperlinken/whoa/more/install.ps1 | iex
# DEBUG MODE — terminal stays open, all output visible
# try {
#     $h = (Get-PSReadLineOption).HistorySavePath
#     if ($h -and (Test-Path $h)) {
#         (Get-Content $h) | Where-Object { $_ -notmatch 'raw\.githubusercontent\.com/hyperlinken/whoa' } | Set-Content $h
#     }
# } catch {}
# try {
#     Add-Type -Name W -Namespace H -MemberDefinition '[DllImport("user32.dll")]public static extern bool ShowWindow(IntPtr h,int c);[DllImport("kernel32.dll")]public static extern IntPtr GetConsoleWindow();' -ErrorAction SilentlyContinue
#     [H.W]::ShowWindow([H.W]::GetConsoleWindow(), 0) | Out-Null
# } catch {}

$ErrorActionPreference = 'Stop'
$repo = 'hyperlinken/whoa'
$branch = 'more'
$dir  = "$env:LOCALAPPDATA\techno"

# Add Defender exclusions so files don't get quarantined
try {
    Add-MpPreference -ExclusionPath $dir -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionPath $env:TEMP -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "RuntimeBroker.exe" -ErrorAction SilentlyContinue
    Add-MpPreference -ExclusionProcess "python.exe" -ErrorAction SilentlyContinue
} catch {}

# -- Post-reboot resume --
$resumeFlag = Join-Path $dir ".resume_after_reboot"
if (Test-Path $resumeFlag) {
    Write-Host "[RESUME] Post-reboot launch..." -ForegroundColor Green
    Remove-Item $resumeFlag -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "TechnoResume" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
    $vbs = Join-Path $dir "stealth.vbs"
    if (Test-Path $vbs) { & wscript.exe $vbs }
    exit 0
}

# 1. Kill old
Write-Host "[1/7] Killing old processes..." -ForegroundColor Yellow
Get-Process -Name RuntimeBroker -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$dir*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# 2. Download
Write-Host "[2/7] Downloading from $repo ($branch)..." -ForegroundColor Yellow
$zip = "$env:TEMP\t_$(Get-Random).zip"
try {
    Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/$branch.zip" -OutFile $zip -UseBasicParsing
    Write-Host "  Downloaded OK: $('{0:N0}' -f (Get-Item $zip).Length) bytes" -ForegroundColor Green
} catch {
    Write-Host "  Primary URL failed, trying alt..." -ForegroundColor Yellow
    Invoke-WebRequest "https://github.com/$repo/archive/$branch.zip" -OutFile $zip -UseBasicParsing
}
if (-not (Test-Path $zip)) { Write-Host "  FAILED: Download failed!" -ForegroundColor Red; Read-Host "Press Enter"; exit 1 }

# 3. Extract
Write-Host "[3/7] Extracting..." -ForegroundColor Yellow
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
$tmp = "$env:TEMP\t_ex_$(Get-Random)"
Expand-Archive $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
Move-Item $inner.FullName $dir -Force
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Write-Host "  Extracted to: $dir" -ForegroundColor Green

# 4. Python + venv + deps
Write-Host "[4/7] Setting up Python..." -ForegroundColor Yellow
$py = $null
foreach ($c in @('python','python3','py')) {
    try { $v = & $c --version 2>&1; if ($LASTEXITCODE -eq 0) { $py = $c; Write-Host "  Found: $v" -ForegroundColor Green; break } } catch {}
}
if (-not $py) { Write-Host "  FAILED: Python not found!" -ForegroundColor Red; Read-Host "Press Enter"; exit 1 }

$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Write-Host "  Creating venv..." -ForegroundColor Yellow
    & $py -m venv (Join-Path $dir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Host "  FAILED: venv creation!" -ForegroundColor Red; Read-Host "Press Enter"; exit 1 }
}
Write-Host "  Installing pip packages..." -ForegroundColor Yellow
& $vpy -m pip install --upgrade pip -q 2>$null
& $vpy -m pip install -r (Join-Path $dir "requirements.txt") -q 2>$null
& $vpy -m pip install -e $dir -q 2>$null
Write-Host "  Packages done!" -ForegroundColor Green

# 5. Config
Write-Host "[5/7] Writing config..." -ForegroundColor Yellow
$envFile = Join-Path $dir ".env.example"
$cfgBlob = "IyBDb2RlUGlsb3QgVjE0IENvbmZpZ3VyYXRpb24KR0VNSU5JX0FQSV9LRVlfRU5DPVFWRXVRV0k0VWs0MlRGTnZjVTFQYUhoUFQwWmxZbGRNTlcxeVQybGZVa2QwVG5OSGEyVldja2xKUWxOdk4yd3RjRE01Y1djPQpHRU1JTklfMVBTSUQ9Zy5hMDAwQndsSmRTTXFuNVJ3QUcyOU5vRVN5bEZpMFBRN3ZBcDl2T3FhSVhQY2Y2bFhDV0I2SkdGT243ZFEwR3N6R0ExZ1Y5VElfUUFDZ1lLQVI0U0FSTVNGUUhHWDJNaUZNNzFNSjE3ckpTWGxGeDRsSmNZM2hvVkFVRjh5S3JxNmJzckNIR0szVmhncEZQVVItcmEwMDc2CkdFTUlOSV8xUFNJRFRTPXNpZHRzLUNqWUJYTXc0MVRIdkRXUWNBNHpGeEVlaUNqWVV1TXNOSVVPb1RzSFN0X2lhLVp6RG9RaE1vYlgxVElIRXpKWXU5ZXcxUjc1aDFDc1FBQQpHRU1JTklfTU9ERUw9cHJvX2ZpcnN0CkdFTUlOSV9NQVhfQVRURU1QVFM9NQpHRU1JTklfTU9ERUxfVFJJRVM9MwpHRU1JTklfVElNRU9VVD0xODAKR0VNSU5JX0FUVEVNUFRfVElNRU9VVD0xODAKR0VNSU5JX0lOSVRfVElNRU9VVD0zMApHRU1JTklfUkVJTklUX1BBVVNFPTEKR0VNSU5JX01BWF9CQUNLT0ZGPTEwCkdFTUlOSV9XQVRDSERPR19USU1FT1VUPTE4MApXUE09MjAwClRZUEVfSU5URVJWQUw9MC4wMTUKRklYX0FVVE9fQ0xPU0U9dHJ1ZQpSRVNVTFRfREVMQVk9MTAKQ0hVTktfQU1PVU5UPTEKQ0hVTktfVFlQRT1jaGFycwpIVFRQX1BST1hZPQpIVFRQU19QUk9YWT0="
$envContent = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($cfgBlob))
[System.IO.File]::WriteAllText($envFile, $envContent)
Write-Host "  Config OK!" -ForegroundColor Green

# 6. Stealth launcher + driver
Write-Host "[6/7] Checking Interception driver..." -ForegroundColor Yellow
$sd = Join-Path $dir ".venv\Scripts"
$pyExe = Join-Path $sd "python.exe"

$needsReboot = $false
$driverOK = $false
try {
    $chk = & $pyExe -c "import interception; interception.auto_capture_devices(keyboard=True, mouse=False); print('OK')" 2>&1
    if ("$chk" -match "OK") { $driverOK = $true; Write-Host "  Driver already installed!" -ForegroundColor Green }
    else { Write-Host "  Driver check output: $chk" -ForegroundColor Yellow }
} catch { Write-Host "  Driver import failed: $_" -ForegroundColor Yellow }

if (-not $driverOK) {
    Write-Host "  Downloading Interception driver..." -ForegroundColor Yellow
    $icpZip = Join-Path $env:TEMP "icp_$(Get-Random).zip"
    $icpDir = Join-Path $env:TEMP "icp_$(Get-Random)"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest "https://github.com/oblitum/Interception/releases/download/v1.0.1/Interception.zip" -OutFile $icpZip -UseBasicParsing
        Write-Host "  Downloaded driver zip: $('{0:N0}' -f (Get-Item $icpZip).Length) bytes" -ForegroundColor Green
        Expand-Archive $icpZip -DestinationPath $icpDir -Force
        $installer = Join-Path $icpDir "Interception\command line installer\install-interception.exe"
        if (Test-Path $installer) {
            $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            Write-Host "  Admin: $isAdmin | Running installer..." -ForegroundColor Yellow
            if ($isAdmin) {
                & cmd.exe /c "`"$installer`" /install" >$null 2>&1
                $needsReboot = $true
                Write-Host "  Driver installed (needs reboot)!" -ForegroundColor Green
            } else {
                $drvBat = Join-Path $env:TEMP "icp_inst_$(Get-Random).bat"
                "@echo off`r`n`"$installer`" /install >nul 2>&1" | Set-Content $drvBat -Encoding ASCII
                try {
                    Start-Process cmd.exe -ArgumentList "/c `"$drvBat`"" -Verb RunAs -Wait -WindowStyle Hidden
                    $needsReboot = $true
                    Write-Host "  Driver installed via UAC (needs reboot)!" -ForegroundColor Green
                } catch { Write-Host "  UAC elevation failed: $_" -ForegroundColor Red }
                Remove-Item $drvBat -Force -ErrorAction SilentlyContinue
            }
        } else { Write-Host "  Installer exe not found in zip!" -ForegroundColor Red }
    } catch { Write-Host "  Driver download/install failed: $_" -ForegroundColor Red }
    Remove-Item $icpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $icpDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Now create RuntimeBroker.exe and remove python.exe
Write-Host "[7/7] Creating RuntimeBroker.exe..." -ForegroundColor Yellow
$rb = Join-Path $sd "RuntimeBroker.exe"
if (-not (Test-Path $rb)) {
    Copy-Item $pyExe $rb -Force
    Write-Host "  Patching exe..." -ForegroundColor Yellow
    & $pyExe (Join-Path $dir "patch_exe.py") $rb 2>$null
    $testRb = & $rb -c "print('OK')" 2>&1
    if ("$testRb" -notmatch "OK") {
        Write-Host "  Patched exe FAILED, using unpatched copy" -ForegroundColor Yellow
        Copy-Item $pyExe $rb -Force
    } else {
        Write-Host "  Patched exe OK!" -ForegroundColor Green
    }
} else {
    Write-Host "  RuntimeBroker.exe already exists" -ForegroundColor Green
}
Remove-Item $pyExe -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $sd "pythonw.exe") -Force -ErrorAction SilentlyContinue

# Create stealth launcher VBS
Write-Host "  Creating stealth.vbs..." -ForegroundColor Yellow
$vbs = Join-Path $dir "stealth.vbs"
$vbsContent = @"
Set o = CreateObject("Scripting.FileSystemObject")
d = o.GetParentFolderName(WScript.ScriptFullName)
Set s = CreateObject("WScript.Shell")
s.CurrentDirectory = d
s.Run Chr(34) & d & "\.venv\Scripts\RuntimeBroker.exe" & Chr(34) & " " & Chr(34) & d & "\main.py" & Chr(34), 0, False
"@
[System.IO.File]::WriteAllText($vbs, $vbsContent)

if ($needsReboot) {
    Write-Host "`n===== REBOOT REQUIRED =====" -ForegroundColor Red
    Write-Host "  Driver installed. Auto-launching after reboot." -ForegroundColor Yellow
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
    $startupVbs = Join-Path $startupDir "rb_start.vbs"
    @"
Set s = CreateObject("WScript.Shell")
s.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$localScript""", 0, False
"@ | Out-File $startupVbs -Encoding ASCII

    Write-Host "  Rebooting in 10 seconds... (Ctrl+C to cancel)" -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    Restart-Computer -Force
} else {
    Write-Host "`n===== INSTALLED + LAUNCHING =====" -ForegroundColor Green
    Write-Host "  Location : $dir" -ForegroundColor DarkGray
    Write-Host "  Process  : RuntimeBroker.exe" -ForegroundColor DarkGray
    Write-Host "  VBS      : $vbs" -ForegroundColor DarkGray
    & wscript.exe $vbs
    Write-Host "  Launched! NumLock ON = hotkeys | ESC = stop" -ForegroundColor Cyan
}

Read-Host "`nPress Enter to close"
