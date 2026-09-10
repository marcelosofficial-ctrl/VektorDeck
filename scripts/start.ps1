$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot '.env'
$venvActivate = Join-Path $repoRoot '.venv\Scripts\activate.bat'
$webDir = Join-Path $repoRoot 'web'

function Import-DotEnv([string]$path) {
    if (-not (Test-Path $path)) {
        throw "Missing .env. Run scripts\configure.ps1 first."
    }
    foreach ($line in Get-Content $path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $parts = $trimmed.Split('=', 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], 'Process')
    }
}

function Wait-ForUrl([string]$url, [int]$seconds = 40) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

Set-Location $repoRoot
Import-DotEnv $envFile

if (-not (Test-Path $venvActivate)) {
    throw "Python environment not found at $venvActivate"
}
if (-not (Test-Path (Join-Path $webDir 'package.json'))) {
    throw 'Frontend package.json not found.'
}

$backendCommand = "title VEKTORDECK BACKEND && cd /d `"$repoRoot`" && call `"$venvActivate`" && vektordeck"
$frontendCommand = "title VEKTORDECK FRONTEND && cd /d `"$webDir`" && npm run dev"

Write-Host 'Starting VektorDeck backend...' -ForegroundColor Green
Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $backendCommand | Out-Null

Write-Host 'Starting VektorDeck frontend...' -ForegroundColor Green
Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $frontendCommand | Out-Null

Write-Host 'Waiting for services...' -ForegroundColor DarkGray
$backendReady = Wait-ForUrl 'http://127.0.0.1:8765/api/health'
$frontendReady = Wait-ForUrl 'http://localhost:5173/'

if ($backendReady -and $frontendReady) {
    Write-Host 'VektorDeck is ready.' -ForegroundColor Green
    Start-Process 'http://localhost:5173/'
} else {
    Write-Warning "Startup timed out. Backend ready: $backendReady | Frontend ready: $frontendReady"
    Write-Host 'Check the VEKTORDECK BACKEND and VEKTORDECK FRONTEND windows for errors.'
}
