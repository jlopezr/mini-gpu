# Lanzador Windows de tools/list-prototypes; usa el python de .venv si existe.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'list-prototypes') @args
exit $LASTEXITCODE
