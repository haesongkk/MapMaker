$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Write-Host 'Paste your RunPod API key. Input is hidden; the key is saved only in this checkout.'
$secret = Read-Host 'RunPod API key' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
    $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
    if ($value.Length -lt 20 -or $value -match '\s') { throw 'Invalid API key format.' }
    $directory = Join-Path $projectRoot '.runtime'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    [IO.File]::WriteAllText((Join-Path $directory 'runpod-api.key'), $value, [Text.UTF8Encoding]::new($false))
    Write-Host 'Saved. You may close this window.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $value = $null
}
Read-Host 'Press Enter to close'
