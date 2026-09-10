$ErrorActionPreference = 'Stop'

function Get-Json([string]$url) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "Unexpected HTTP $($response.StatusCode) from $url"
    }
    return ($response.Content | ConvertFrom-Json)
}

function Assert-Endpoint([string]$label, [string]$url) {
    try {
        $payload = Get-Json $url
        Write-Host ("PASS  {0}" -f $label) -ForegroundColor Green
        return $payload
    } catch {
        Write-Host ("FAIL  {0} · {1}" -f $label, $_.Exception.Message) -ForegroundColor Red
        throw
    }
}

Write-Host ''
Write-Host 'VEKTORDECK LIVE SMOKE CHECK' -ForegroundColor Cyan
Write-Host 'Read-only validation. No models or runtimes will be launched.' -ForegroundColor DarkGray

$health = Assert-Endpoint 'Backend health' 'http://127.0.0.1:8765/api/health'
if ($health.status -ne 'ok') { throw "Backend status is '$($health.status)' instead of 'ok'." }
if ($health.database -ne 'ok') { throw "SQLite health is '$($health.database)' instead of 'ok'." }

$models = Assert-Endpoint 'Model inventory API' 'http://127.0.0.1:8765/api/models'
$profiles = Assert-Endpoint 'Profile API' 'http://127.0.0.1:8765/api/profiles'
$runtimes = Assert-Endpoint 'Runtime API' 'http://127.0.0.1:8765/api/runtimes'
$telemetry = Assert-Endpoint 'Telemetry API' 'http://127.0.0.1:8765/api/telemetry'
$readiness = Assert-Endpoint 'Release readiness API' 'http://127.0.0.1:8765/api/release-readiness'

if ($null -eq $models) { throw 'Model inventory response was empty.' }
if ($null -eq $profiles) { throw 'Profile response was empty.' }
if ($null -eq $runtimes) { throw 'Runtime response was empty.' }
if ($null -eq $telemetry) { throw 'Telemetry response was empty.' }
if ($null -eq $readiness.status) { throw 'Release readiness response did not contain status.' }

try {
    $frontend = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:5173/' -TimeoutSec 5
    if ($frontend.StatusCode -lt 200 -or $frontend.StatusCode -ge 400) {
        throw "Unexpected HTTP $($frontend.StatusCode)"
    }
    Write-Host 'PASS  Frontend HTTP' -ForegroundColor Green
} catch {
    Write-Host ("FAIL  Frontend HTTP · {0}" -f $_.Exception.Message) -ForegroundColor Red
    throw
}

Write-Host ''
Write-Host ("Smoke check passed · backend {0} · readiness {1}" -f $health.version, $readiness.status) -ForegroundColor Green
