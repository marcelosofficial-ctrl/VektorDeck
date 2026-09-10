$ErrorActionPreference = 'SilentlyContinue'

$repoRoot = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$reportPath = Join-Path $desktop 'VektorDeck-Diagnostics.txt'
$lines = New-Object System.Collections.Generic.List[string]

function Add-Line([string]$text = '') { $lines.Add($text) }
function Add-Section([string]$title) {
    Add-Line ''
    Add-Line ('=' * 72)
    Add-Line $title
    Add-Line ('=' * 72)
}
function Capture([scriptblock]$block) {
    try { return ((& $block 2>&1 | Out-String).Trim()) } catch { return "ERROR: $($_.Exception.Message)" }
}
function Get-LocalJson([string]$url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5
        return ($response.Content | ConvertFrom-Json)
    } catch { return $null }
}
function Value-Or([object]$value, [string]$fallback = '-') {
    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) { return $fallback }
    return [string]$value
}

Set-Location $repoRoot
Add-Line 'VEKTORDECK DIAGNOSTICS'
Add-Line ("Generated: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))
Add-Line 'This report intentionally does not include .env contents or credentials.'

Add-Section 'REPOSITORY'
Add-Line ("Path: {0}" -f $repoRoot)
Add-Line ("Branch: {0}" -f (Capture { git branch --show-current }))
Add-Line ("Commit: {0}" -f (Capture { git rev-parse HEAD }))
Add-Line ("Status:`n{0}" -f (Capture { git status --short }))

Add-Section 'VERSIONS'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $python) {
    Add-Line ("Python: {0}" -f (Capture { & $python --version }))
    Add-Line ("VektorDeck package: {0}" -f (Capture { & $python -c "import vektordeck; print(vektordeck.__version__)" }))
} else { Add-Line 'Python environment: NOT FOUND' }
Add-Line ("Node: {0}" -f (Capture { node --version }))
Add-Line ("npm: {0}" -f (Capture { npm.cmd --version }))
Add-Line ("Git: {0}" -f (Capture { git --version }))

Add-Section 'PORTS / PROCESSES'
foreach ($port in @(8765, 5173, 8080, 7860)) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listeners) {
        foreach ($listener in $listeners) {
            $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
            $processName = if ($null -ne $process) { $process.ProcessName } else { 'unknown' }
            Add-Line ("Port {0}: LISTENING · PID {1} · {2}" -f $port, $listener.OwningProcess, $processName)
        }
    } else { Add-Line ("Port {0}: free" -f $port) }
}

Add-Section 'BACKEND HEALTH'
$health = Get-LocalJson 'http://127.0.0.1:8765/api/health'
if ($health) {
    Add-Line ("Status: {0}" -f $health.status)
    Add-Line ("Version: {0}" -f $health.version)
    Add-Line ("Database: {0}" -f $health.database)
} else { Add-Line 'Backend health endpoint: unavailable' }

Add-Section 'RUNTIMES'
$runtimes = Get-LocalJson 'http://127.0.0.1:8765/api/runtimes'
if ($runtimes) {
    foreach ($runtime in $runtimes) {
        $ownership = if ($runtime.recovered) { 'RECOVERED' } elseif ($runtime.running) { 'MANAGED' } else { 'IDLE' }
        Add-Line ("{0}: state={1} configured={2} exists={3} running={4} pid={5}" -f $runtime.label, $ownership, $runtime.configured, $runtime.exists, $runtime.running, (Value-Or $runtime.pid))
        Add-Line ("  path: {0}" -f (Value-Or $runtime.path))
    }
} else { Add-Line 'Runtime endpoint: unavailable' }

Add-Section 'MACHINE SNAPSHOT'
$telemetry = Get-LocalJson 'http://127.0.0.1:8765/api/telemetry'
if ($telemetry) {
    Add-Line ("CPU: {0}%" -f $telemetry.cpu.utilization_percent)
    Add-Line ("RAM: {0}% · used={1} · total={2}" -f $telemetry.memory.percent, $telemetry.memory.used_bytes, $telemetry.memory.total_bytes)
    Add-Line ("GPU: {0} · {1}%" -f $telemetry.gpu.name, $telemetry.gpu.utilization_percent)
    Add-Line ("VRAM: used={0} · total={1}" -f $telemetry.gpu.vram_used_bytes, $telemetry.gpu.vram_total_bytes)
} else { Add-Line 'Telemetry endpoint: unavailable' }

Add-Section 'TOP PROCESSES (READ ONLY)'
$processPayload = Get-LocalJson 'http://127.0.0.1:8765/api/processes/top?limit=8'
if ($processPayload -and $processPayload.processes) {
    foreach ($item in $processPayload.processes) {
        Add-Line ("{0} · PID {1} · CPU {2}% · RAM {3} MB" -f $item.name, $item.pid, $item.cpu_percent, $item.memory_mb)
    }
} else { Add-Line 'Process inspector endpoint: unavailable or empty' }

Add-Section 'RECENT BENCHMARKS'
$benchmarks = Get-LocalJson 'http://127.0.0.1:8765/api/benchmarks?limit=10'
$protocols = Get-LocalJson 'http://127.0.0.1:8765/api/benchmark-protocol?limit=100'
if ($benchmarks) {
    foreach ($run in $benchmarks) {
        $speed = if ($null -ne $run.server_tokens_per_second) { $run.server_tokens_per_second } else { $run.tokens_per_second }
        $protocol = $null
        if ($protocols) { $protocol = $protocols | Where-Object { $_.benchmark_id -eq $run.id } | Select-Object -First 1 }
        $protocolText = if ($protocol) { "v$($protocol.protocol_version)/$($protocol.run_source)/baseline=$($protocol.baseline_ready)" } else { 'legacy' }
        Add-Line ("#{0} · {1} · {2} tok/s · quality={3} · protocol={4} · RAM avg={5}% peak={6}% · VRAM peak={7}" -f $run.id, $run.profile_name, $speed, (Value-Or $run.quality), $protocolText, (Value-Or $run.ram_avg_percent), (Value-Or $run.ram_peak_percent), (Value-Or $run.vram_peak_bytes))
    }
} else { Add-Line 'Benchmark endpoint: unavailable' }

Add-Section 'LLAMA LOG TAIL'
$logPayload = Get-LocalJson 'http://127.0.0.1:8765/api/runtimes/llama.cpp/logs?lines=100'
if ($logPayload -and $logPayload.lines) {
    Add-Line ("Path: {0}" -f $logPayload.path)
    foreach ($line in $logPayload.lines) { Add-Line ([string]$line) }
} else {
    $fallbackLog = Join-Path $env:USERPROFILE '.vektordeck\logs\llama.cpp.log'
    if (Test-Path $fallbackLog) {
        Add-Line ("Fallback path: {0}" -f $fallbackLog)
        $ansi = [regex]'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'
        Get-Content $fallbackLog -Tail 100 | ForEach-Object { Add-Line ($ansi.Replace($_, '')) }
    } else { Add-Line 'No llama.cpp log available.' }
}

Add-Section 'END'
Add-Line 'Attach or paste this report when asking for VektorDeck troubleshooting help.'
$lines | Set-Content -Path $reportPath -Encoding UTF8
Write-Host ''
Write-Host 'Diagnostics complete.' -ForegroundColor Green
Write-Host "Saved to: $reportPath" -ForegroundColor Cyan
Start-Process explorer.exe "/select,`"$reportPath`""
