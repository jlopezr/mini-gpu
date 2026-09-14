# Lanzador Windows de tools/cpusim; usa el python de .venv si existe.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'cpusim') @args
exit $LASTEXITCODE
