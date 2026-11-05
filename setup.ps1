# TrojanCut setup for Windows 10/11 (PowerShell). Installs ffmpeg, Python 3.12 and Node 22 with winget
# when missing, runs `tc.py setup`, and installs both skills into %USERPROFILE%\.claude\skills.
# Safe to run again. Run from the repo folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
function Winget-Install($id) {
    if (-not (Have "winget")) { throw "winget is not available. Install 'App Installer' from the Microsoft Store, then run this again." }
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

if (-not (Have "ffmpeg")) { Write-Host "Installing ffmpeg ..."; Winget-Install "Gyan.FFmpeg" }
$py = $null
foreach ($c in @("python", "py")) {
    if (Have $c) {
        $v = & $c --version 2>$null
        if ($v -match "Python 3\.(1[0-9])") { $py = $c; break }
    }
}
if (-not $py) { Write-Host "Installing Python 3.12 ..."; Winget-Install "Python.Python.3.12"; $py = "python" }
if (-not (Have "node")) { Write-Host "Installing Node.js 22 (enables the HyperFrames engine) ..."; Winget-Install "OpenJS.NodeJS.LTS" }

& $py skills\trojancut\scripts\tc.py setup
if ($LASTEXITCODE -ne 0) { throw "tc.py setup failed" }
$dest = Join-Path $env:USERPROFILE ".claude\skills"
& $py skills\trojancut\scripts\tc.py install-skills --dest $dest
if ($LASTEXITCODE -ne 0) { throw "installing the skills failed" }
# install-skills copies skills\trojancut and skills\templatetrojancut into $dest
Write-Host "Done. Restart Claude Code, then use /templatetrojancut and /trojancut."
