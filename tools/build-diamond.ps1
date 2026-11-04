# Lanzador Windows de `tools/diamond_runner.py`; reenvía tal cual.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$env:PYTHONPATH = $root
& $python -m tools.diamond_runner @args
exit $LASTEXITCODE
