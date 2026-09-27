param([int]$Port = 8082)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:MAPMAKER_BACKEND = 'runpod'
$localCredentials = Join-Path $projectRoot '.runtime\runpod-s3.credentials'
if (Test-Path -LiteralPath $localCredentials) {
    $env:AWS_SHARED_CREDENTIALS_FILE = $localCredentials
}
& "$projectRoot\.venv\Scripts\python.exe" -m mapmaker.web --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
