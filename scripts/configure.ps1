$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

Write-Host ''
Write-Host 'VektorDeck local configuration' -ForegroundColor Green
Write-Host 'These paths are stored only in .env on this machine.' -ForegroundColor DarkGray
Write-Host ''

$modelRoot = Read-Host 'Model root (example: M:\LocalAI\models)'
$llamaServer = Read-Host 'llama-server.exe path'
$a1111Root = Read-Host 'Stable Diffusion / A1111 root'
$gpuVram = Read-Host 'GPU VRAM capacity in GB (optional, example: 16)'

$lines = @(
    "VEKTORDECK_MODEL_ROOTS=$modelRoot",
    "VEKTORDECK_LLAMA_SERVER=$llamaServer",
    "VEKTORDECK_A1111_ROOT=$a1111Root"
)

if ($gpuVram) {
    $lines += "VEKTORDECK_GPU_VRAM_GB=$gpuVram"
}

Set-Content -Path $envPath -Value $lines -Encoding UTF8

Write-Host ''
Write-Host "Saved local configuration to $envPath" -ForegroundColor Green
Write-Host 'Git ignores this file, so these machine-specific paths will not be published.' -ForegroundColor DarkGray
