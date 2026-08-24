# CodePilot V14 — One-Line Install + Stealth Launch (Zero Input)
# Usage: powershell -c "irm https://raw.githubusercontent.com/hyperlinken/whoa/more/install.ps1 | iex"
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
Add-Type -AssemblyName System.IO.Compression
$cfgBlob = "H4sIAAAAAAAEAO1W3W6rRhC+z1OsdC6aSLYD/o8lpBIMBjv82IB/TlUhDGubGrOEXfyTqlLVJ+gL9OZc9ynaNzlP0oGTpCeKL1ud/uQCDTu7++3szDcz+w79/uHjjx9++/lN/JfExTskkRBbUUwYmvJNGCWraJ1nPotIArP/CCvfxF8c9cfA/vLxp1+fJBItDY3wCV0ufYrbTYSTAJgRIkZQmuE9ThgaREzNl8jPGamCigQlS65eYQG8mKYoxAUCRWwT0XLTDtYHfhyfkM8QZX7G8vRiIOuaoXlwvDeSF55sSMJ4KufjmdZ0t926oxj7wOUtX91YDvc+XsShbsz4k1OPV+425JzEUP36dBZs4+E4NvZG/cCCvt4KZoFw9p5mWhiN6j3gOtlGuFrcN0QzvCxdcJkncbSLGA4rKCEIEgGjUkHP3nOSJz2UntgGICmG+3prvIuSqJaeCs+BCp1InqGgPIvWnq7LW7bWF9Y1n+O420M8DG39PmlNDuKgfmMQ2T7FSsRZ485eTG/25r2vza1g1Y7n0uy2PRwoZtIJx9yAPgxEfj29cTRvLErrxUicNG1xotvKWB3M63qk6B1eH/KdbGjPY+XYjIfBorEhU9FVuqdRdt9e0kxSB6PGdLNOFcudVDOwqNN+YaZjCzQKGa1K3y1u5/qhyTvqvj8bB2LzQTnKOAK9m+vU0FyTOFS1mRf51fcPfTLe6GQ55x1NlR+Gi/wGH/hJp7XhJToWxbPR0YExMbIxY1Gypq/m3+TfK5/irpt9+U5IM+KtooyyZ7U490THkXULONF6sdhzJppsC40npaPpsuk6At/lnlP8085zU/D9qW88qydyOWGJri0L/OdW3IrSyFQUgX9eOxMdSe2bgxfw5yjmnFLgFrJTDGn/pR3+f5cQoJmlo8sDyUKKUpwhqJ45w1c11OAEGpNDBbU5YeVTVkE8xwl7nJ3Qp2Edhjv/eAEAAvwDlIWzarDxMz9ggASVxId+RqENJSEFRDOB1pMX1T5alcdCX+JqF87CkoGBjjyZincCV+P4FmAp0RHhMGIkKzoYNKyy7QUxoRgt4YQtZhR9/0MFXV5V0Dff1i4UDZLDdUxPujOBrizL8fkGxDZg3FuJ+1KMm8i2e+d4ULPERVE/JNU1Rp6om64BReNxWHBCKKhEz8bQysgRqBWQOMZrfB2QLCXlUyHBDKi8PfNY+LdLcIO2Kh4zX2WQAHgTJSHy4WkIjqiU7xygNcU1JB/9XRpj2oMNCG0YS3vX1+Wy2qO7ajjMe12uy32+AtIyS/wd7qU+pUU1+Pr1ngZf75Z7KAm2tHUWly9wVcexPGtizhdC+W8/Df4A4jRDQMcOAAA="
$compressed = [Convert]::FromBase64String($cfgBlob)
$ms = [System.IO.MemoryStream]::new($compressed)
$gz = [System.IO.Compression.GZipStream]::new(
    $ms,
    [System.IO.Compression.CompressionMode]::Decompress
)
$sr = [System.IO.StreamReader]::new($gz)
$envContent = $sr.ReadToEnd()
$sr.Close()
[System.IO.File]::WriteAllText($envFile, $envContent)
Write-Host "  Config ready!" -ForegroundColor Green

# 6. Stealth launcher + driver
Write-Host "[5/6] Creating launcher..." -ForegroundColor Yellow
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

# Try Interception driver (optional)
Write-Host "[6/6] Checking driver..." -ForegroundColor Yellow
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
