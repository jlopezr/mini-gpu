# Lanzador Windows de tools/setup; usa el python de .venv si existe (es el que recibe los paquetes).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'setup') @args
exit $LASTEXITCODE
