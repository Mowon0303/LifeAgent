# Windows entry point for the live verification preflight.
# Same sequence, same SENTINEL_LIVE_* environment variables, and the same exit
# codes as scripts/live_verification_preflight.sh — no Bash required.
#
#   $env:SENTINEL_LIVE_DRY_RUN = "1"
#   .\scripts\live_verification_preflight.ps1

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$PythonBin = $env:SENTINEL_LIVE_PYTHON
if (-not $PythonBin) {
    $VenvPython = Join-Path $RootDir ".agent-venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $PythonBin = $VenvPython
    }
    else {
        $Fallback = Get-Command python -ErrorAction SilentlyContinue
        if (-not $Fallback) {
            Write-Error "No Python runtime found. Set SENTINEL_LIVE_PYTHON or create .agent-venv (see README)."
            exit 2
        }
        $PythonBin = $Fallback.Source
        Write-Warning "Using fallback Python runtime: $PythonBin"
        Write-Warning "Create the project venv with: python -m venv .agent-venv; .\.agent-venv\Scripts\python.exe -m pip install -e '.[agent,integrations]'"
    }
}

$env:SENTINEL_LIVE_PYTHON = $PythonBin
Set-Location $RootDir
& $PythonBin -B -m sentineldesk integrations preflight
exit $LASTEXITCODE
