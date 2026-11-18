# Lanzador Windows de `tools/phase_sweep.py`; reenvía tal cual.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$env:PYTHONPATH = $root
& $python -m tools.phase_sweep @args
exit $LASTEXITCODE
