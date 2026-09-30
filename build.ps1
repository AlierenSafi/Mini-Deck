$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    python tools/build.py
    if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed' }
} finally { Pop-Location }
