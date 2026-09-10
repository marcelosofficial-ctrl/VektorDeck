$ErrorActionPreference = 'SilentlyContinue'

$repoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-LocalPost([string]$url) {
    try {
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri $url -TimeoutSec 4 | Out-Null
    } catch {}
}

function Stop-Tree([int]$processId) {
    if ($processId -le 0) { return }
    & taskkill.exe /PID $processId /T /F *> $null
}

function Get-PortOwner([int]$port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) { return $null }

    $processId = [int]$listener.OwningProcess
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue

    return [pscustomobject]@{
        Port = $port
        ProcessId = $processId
        Name = if ($null -ne $process) { [string]$process.ProcessName } else { $null }
        ExecutablePath = if ($null -ne $cim) { [string]$cim.ExecutablePath } else { $null }
        CommandLine = if ($null -ne $cim) { [string]$cim.CommandLine } else { $null }
    }
}

function Test-IsVektorDeckProcess([object]$owner) {
    if ($null -eq $owner) { return $false }

    $repoNeedle = $repoRoot.ToLowerInvariant()
    $path = ([string]$owner.ExecutablePath).ToLowerInvariant()
    $command = ([string]$owner.CommandLine).ToLowerInvariant()
    $name = ([string]$owner.Name).ToLowerInvariant()

    if ($path.Contains($repoNeedle) -or $command.Contains($repoNeedle)) { return $true }
    if ($command.Contains('vektordeck') -and $owner.Port -eq 8765) { return $true }
    if (($name -in @('node', 'node.exe')) -and $command.Contains('vite') -and $owner.Port -eq 5173) { return $true }
    return $false
}

function Stop-OrphanedVektorDeckPort([int]$port) {
    $owner = Get-PortOwner $port
    if ($null -eq $owner) { return }

    if (Test-IsVektorDeckProcess $owner) {
        Write-Host ("Cleaning orphaned VektorDeck process on port {0}: {1} PID {2}" -f $port, $owner.Name, $owner.ProcessId) -ForegroundColor DarkGray
        Stop-Tree $owner.ProcessId
        Start-Sleep -Milliseconds 500
        return
    }

    Write-Warning ("Port {0} is still owned by a process that VektorDeck cannot safely identify as its own: {1} PID {2}" -f $port, $owner.Name, $owner.ProcessId)
}

# Ask the running backend to stop only AI runtimes VektorDeck owns first.
Invoke-LocalPost 'http://127.0.0.1:8765/api/workspace/stop'
Invoke-LocalPost 'http://127.0.0.1:8765/api/runtimes/a1111/stop'
Start-Sleep -Milliseconds 700

# Kill the complete process trees for launcher-created consoles.
$windows = Get-Process cmd -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -in @('VEKTORDECK BACKEND', 'VEKTORDECK FRONTEND')
}
foreach ($window in $windows) {
    Stop-Tree $window.Id
}

Start-Sleep -Milliseconds 700

# If a child detached from its original console, recover by inspecting the
# actual listeners. Only kill when the OS evidence ties the process back to
# this VektorDeck checkout.
Stop-OrphanedVektorDeckPort 8765
Stop-OrphanedVektorDeckPort 5173

Write-Host 'VektorDeck stopped.' -ForegroundColor Green
