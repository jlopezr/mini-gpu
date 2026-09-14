# Lanzador global de run_board.py; prefiere el python de .venv porque necesita
# pyserial.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'run_board.py') @args
exit $LASTEXITCODE
