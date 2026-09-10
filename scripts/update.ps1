$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$webDir = Join-Path $repoRoot 'web'
$startScript = Join-Path $repoRoot 'scripts\start.ps1'
$stopScript = Join-Path $repoRoot 'scripts\stop.ps1'
$smokeScript = Join-Path $repoRoot 'scripts\smoke.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$transcriptPath = Join-Path $desktop 'VektorDeck-Update-Last.txt'
$transcriptStarted = $false

function Step([string]$message) {
    Write-Host ''
    Write-Host "==> $message" -ForegroundColor Green
}

function Test-PortInUse([int]$port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    return $null -ne $listener
}

function Wait-PortFree([int]$port, [int]$seconds = 10) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-PortInUse $port)) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return -not (Test-PortInUse $port)
}

function File-Hash([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    return (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLowerInvariant()
}

try {
    Start-Transcript -Path $transcriptPath -Force | Out-Null
    $transcriptStarted = $true
    Write-Host "Update log: $transcriptPath" -ForegroundColor DarkGray

    Set-Location $repoRoot

    $updaterPath = $PSCommandPath
    $updaterHashBeforePull = File-Hash $updaterPath

    Step 'Pulling latest updater and application code from GitHub'
    & git pull
    if ($LASTEXITCODE -ne 0) { throw 'git pull failed.' }

    $updaterHashAfterPull = File-Hash $updaterPath
    if (
        $env:VEKTORDECK_UPDATE_REEXEC -ne '1' -and
        $updaterHashBeforePull -and
        $updaterHashAfterPull -and
        $updaterHashBeforePull -ne $updaterHashAfterPull
    ) {
        Write-Host ''
        Write-Host 'Updater changed during pull; restarting once with the new updater code...' -ForegroundColor Cyan
        if ($transcriptStarted) {
            try { Stop-Transcript | Out-Null } catch {}
            $transcriptStarted = $false
        }
        $env:VEKTORDECK_UPDATE_REEXEC = '1'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updaterPath
        exit $LASTEXITCODE
    }

    Step 'Stopping VektorDeck-managed runtimes and app windows'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopScript

    Step 'Verifying old services are gone'
    $backendFree = Wait-PortFree 8765
    $frontendFree = Wait-PortFree 5173
    if (-not $backendFree -or -not $frontendFree) {
        throw "Could not free VektorDeck ports. 8765 free: $backendFree | 5173 free: $frontendFree. A listener remains and was not safe to terminate automatically."
    }
    Write-Host 'Ports 8765 and 5173 are free.' -ForegroundColor DarkGray

    if (-not (Test-Path $python)) {
        throw "Python environment not found at $python"
    }
    $pyproject = Join-Path $repoRoot 'pyproject.toml'
    if (-not (Test-Path $pyproject)) { throw 'pyproject.toml not found.' }
    $packageJson = Join-Path $webDir 'package.json'
    if (-not (Test-Path $packageJson)) { throw 'Frontend package.json not found.' }
    if (-not (Test-Path $smokeScript)) { throw 'scripts\smoke.ps1 not found.' }

    Step 'Checking Python dependencies'
    $pythonHashMarker = Join-Path $repoRoot '.venv\.vektordeck-pyproject.sha256'
    $pythonHash = File-Hash $pyproject
    $savedPythonHash = if (Test-Path $pythonHashMarker) { (Get-Content $pythonHashMarker -Raw).Trim() } else { '' }
    if ($savedPythonHash -ne $pythonHash) {
        Write-Host 'Python manifest changed (or first tracked update); syncing dependencies...' -ForegroundColor DarkGray
        & $python -m pip install --disable-pip-version-check -e '.[dev]'
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency sync failed.' }
        Set-Content -Path $pythonHashMarker -Value $pythonHash -Encoding ASCII
    } else {
        Write-Host 'Python dependency manifest unchanged; skipping reinstall.' -ForegroundColor DarkGray
    }

    Step 'Running Python test suite'
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed. VektorDeck was not relaunched.' }

    Step 'Checking frontend dependencies and build'
    Push-Location $webDir
    try {
        $nodeModules = Join-Path $webDir 'node_modules'
        $frontendHashMarker = Join-Path $nodeModules '.vektordeck-package.sha256'
        $frontendHash = File-Hash $packageJson
        $savedFrontendHash = if (Test-Path $frontendHashMarker) { (Get-Content $frontendHashMarker -Raw).Trim() } else { '' }
        if (-not (Test-Path $nodeModules) -or $savedFrontendHash -ne $frontendHash) {
            Write-Host 'Frontend manifest changed (or first tracked update); syncing dependencies...' -ForegroundColor DarkGray
            & npm.cmd install
            if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
            Set-Content -Path $frontendHashMarker -Value $frontendHash -Encoding ASCII
        } else {
            Write-Host 'Frontend dependency manifest unchanged; skipping npm install.' -ForegroundColor DarkGray
        }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed. VektorDeck was not relaunched.' }
    } finally {
        Pop-Location
    }

    Step 'Relaunching VektorDeck'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript

    Step 'Running live post-relaunch smoke check'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $smokeScript
    if ($LASTEXITCODE -ne 0) { throw 'Live smoke check failed after relaunch.' }

    Write-Host ''
    Write-Host 'Update complete.' -ForegroundColor Green
    Write-Host 'Tests, production build and live smoke check passed.' -ForegroundColor Green
    Write-Host 'Future updates can be done by double-clicking Update VektorDeck.cmd.' -ForegroundColor DarkGray
    Write-Host "A copy of this update session is saved at: $transcriptPath" -ForegroundColor DarkGray
} catch {
    Write-Host ''
    Write-Host 'UPDATE FAILED' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full update log: $transcriptPath" -ForegroundColor Yellow
    throw
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch {}
    }
}
