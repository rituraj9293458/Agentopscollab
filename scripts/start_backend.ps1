param(
    [int]$Port = 8000,
    [switch]$NoReload
)

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$arguments = @(
    '-m', 'uvicorn', 'raceproof.api:app',
    '--host', '127.0.0.1',
    '--port', $Port.ToString()
)

if (-not $NoReload) {
    # Candidate and verification copies contain Python files. Watching the repository root
    # would restart the API during a run and erase its intentionally in-memory run registry.
    $arguments += @('--reload', '--reload-dir', 'src/raceproof')
}

& python @arguments
