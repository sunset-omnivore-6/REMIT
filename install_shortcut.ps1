# Creates a "REMIT" desktop shortcut that launches REMIT.bat.
#
# Run once after cloning:
#   Right-click this file > Run with PowerShell
# If Windows blocks it:
#   powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
#
# What it does:
#   1. Resolves the repo root from this script's location.
#   2. Optionally creates a .venv and installs requirements.
#   3. Drops a REMIT.lnk on the Desktop pointing at REMIT.bat.
#   4. Uses REMIT.ico for the icon if present, otherwise the default.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath  = Join-Path $repoRoot "REMIT.bat"
$iconPath = Join-Path $repoRoot "REMIT.ico"
$desktop  = [Environment]::GetFolderPath("Desktop")
$lnkPath  = Join-Path $desktop "REMIT.lnk"

Write-Host ""
Write-Host "REMIT setup"
Write-Host "  Repo:    $repoRoot"
Write-Host "  Desktop: $desktop"
Write-Host ""

# --- Step 1: optional virtualenv -------------------------------------------
$createVenv = Read-Host "Create a project-local .venv and install requirements now? [Y/n]"
if ($createVenv -eq "" -or $createVenv -match "^[Yy]") {
    $py = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $py) {
        Write-Host "Python not found on PATH. Install Python 3.11+ from python.org first." -ForegroundColor Red
        exit 1
    }
    Push-Location $repoRoot
    try {
        if (-not (Test-Path ".venv")) {
            Write-Host "Creating .venv..."
            python -m venv .venv
        }
        Write-Host "Installing requirements..."
        & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
        & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
    } finally {
        Pop-Location
    }
}

# --- Step 2: create the shortcut -------------------------------------------
$wshShell  = New-Object -ComObject WScript.Shell
$shortcut  = $wshShell.CreateShortcut($lnkPath)
$shortcut.TargetPath       = $batPath
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle      = 1   # normal window
$shortcut.Description      = "REMIT — Aldbrough & Atwick gas storage outages"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host ""
Write-Host "Desktop shortcut created: $lnkPath" -ForegroundColor Green
Write-Host "Double-click 'REMIT' on your desktop to launch."
Write-Host ""
