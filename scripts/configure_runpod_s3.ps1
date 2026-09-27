$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'MapMaker - RunPod S3 setup'
$projectRoot = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $projectRoot '.runtime\runpod-s3.credentials'
Write-Host 'Copy the Access key and Secret from RunPod > Credentials > S3 API Keys.'
Write-Host 'Credentials will be saved locally under .runtime (excluded from Git).'
$accessKey = (Read-Host 'Access key (user_...)').Trim()
$secretInput = Read-Host 'Secret (rps_...)' -AsSecureString
$secretKey = [System.Net.NetworkCredential]::new('', $secretInput).Password.Trim()
if ($accessKey -notmatch '^user_[A-Za-z0-9_-]+$' -or $secretKey -notmatch '^rps_[A-Za-z0-9_-]+$') {
    throw 'The key format does not match RunPod S3 credentials. Nothing was saved.'
}
New-Item -ItemType Directory -Force (Split-Path -Parent $destination) | Out-Null
[System.IO.File]::WriteAllText($destination, "[default]`naws_access_key_id = $accessKey`naws_secret_access_key = $secretKey`n")
$secretKey = $null
$secretInput.Dispose()
Write-Host 'Saved. Return to Codex and say: done.' -ForegroundColor Green
Read-Host 'Press Enter to close'
