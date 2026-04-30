$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $root 'dist'
$stageDir = Join-Path $distDir 'encar_soldout_monitor_docker'
$zipPath = Join-Path $distDir 'encar_soldout_monitor_docker.zip'

if (Test-Path $stageDir) {
    Remove-Item -LiteralPath $stageDir -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

$excludeNames = @(
    '.venv',
    '__pycache__',
    'dist',
    'soldout_logs',
    '.git',
    '.claude',
    'nul',
    '.env'
)

Get-ChildItem -LiteralPath $root -Force | Where-Object {
    $excludeNames -notcontains $_.Name
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $stageDir -Recurse -Force
}

Compress-Archive -Path (Join-Path $stageDir '*') -DestinationPath $zipPath -Force
Write-Host "Created: $zipPath"
