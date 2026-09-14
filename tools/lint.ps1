# Lanzador Windows de `apio lint` para un prototipo (tools/test --lint-only).
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'test.ps1') --lint-only @args
exit $LASTEXITCODE
