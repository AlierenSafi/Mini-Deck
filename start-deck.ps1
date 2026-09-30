param([string]$Port = "", [switch]$DryRun, [switch]$Preview)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$runtime = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $runtime)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python sanal ortam olusturulamadi." }
}
& $runtime -c "import importlib.util, sys; sys.exit(0 if all(importlib.util.find_spec(m) for m in ('serial', 'psutil', 'PIL', 'pystray', 'discord', 'pycaw', 'comtypes')) else 1)"
if ($LASTEXITCODE -ne 0) {
    & $runtime -m pip install -r companion\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Bagimliliklar kurulamadi." }
}
$launchArgs = @("companion\app.py")
if ($Port) { $launchArgs += @("--port", $Port) }
if ($DryRun) { $launchArgs += "--dry-run" }
if ($Preview) { $launchArgs += "--preview" }
& $runtime @launchArgs
