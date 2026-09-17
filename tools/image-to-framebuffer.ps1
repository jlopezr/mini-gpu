# Lanzador Windows de tools/image-to-framebuffer; usa el python de .venv si existe.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python (Join-Path $PSScriptRoot 'image-to-framebuffer') @args
exit $LASTEXITCODE
