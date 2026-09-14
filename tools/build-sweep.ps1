# Lanzador Windows de `tools/build_runner.py sweep`; reenvía tal cual.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$env:PYTHONPATH = $root
& $python -m tools.build_runner sweep @args
exit $LASTEXITCODE
