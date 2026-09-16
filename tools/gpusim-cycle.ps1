# Lanzador Windows; toda la lógica vive en el simulador.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'gpusim-cycle') @args
exit $LASTEXITCODE
