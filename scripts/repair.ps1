$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $repoRoot '.venv'
$python = Join-Path $venvDir 'Scripts\python.exe'
$webDir = Join-Path $repoRoot 'web'
$stopScript = Join-Path $repoRoot 'scripts\stop.ps1'
$startScript = Join-Path $repoRoot 'scripts\start.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$logPath = Join-Path $desktop 'VektorDeck-Repair-Last.txt'
$transcriptStarted = $false

function Step([string]$message) {
    Write-Host ''
    Write-Host "==> $message" -ForegroundColor Green
}

try {
    Start-Transcript -Path $logPath -Force | Out-Null
    $transcriptStarted = $true
    Set-Location $repoRoot

    Step 'Stopping VektorDeck-managed runtimes and app windows'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript

    if (-not (Test-Path $python)) {
        Step 'Python environment missing; creating .venv with Python 3.11'
        & py -3.11 -m venv $venvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $python)) {
            throw 'Could not create .venv with Python 3.11.'
        }
    }

    Step 'Refreshing Python packaging tools'
    & $python -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw 'Python packaging-tool update failed.' }

    Step 'Installing VektorDeck Python dependencies'
    & $python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

    if (-not (Test-Path (Join-Path $webDir 'package.json'))) {
        throw 'Frontend package.json not found.'
    }

    Step 'Refreshing frontend dependencies'
    Push-Location $webDir
    try {
        & npm.cmd install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
    } finally {
        Pop-Location
    }

    Step 'Running Python tests'
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed. Repair stopped before relaunch.' }

    Step 'Running frontend production build'
    Push-Location $webDir
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. Repair stopped before relaunch.' }
    } finally {
        Pop-Location
    }

    Step 'Relaunching VektorDeck'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript

    Write-Host ''
    Write-Host 'Repair complete.' -ForegroundColor Green
    Write-Host 'Your .env, SQLite data, profiles, benchmarks and model files were not deleted.' -ForegroundColor DarkGray
    Write-Host "Repair log: $logPath" -ForegroundColor DarkGray
} catch {
    Write-Host ''
    Write-Host 'REPAIR FAILED' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full repair log: $logPath" -ForegroundColor Yellow
    throw
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}
