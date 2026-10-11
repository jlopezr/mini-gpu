# Lanzador Windows de tools/build-vlink.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$vlinkDir = Join-Path $root 'w.vlink'

if (-not (Test-Path (Join-Path $vlinkDir 'Makefile'))) {
  Write-Error "No existe $vlinkDir\Makefile. Inicializa el submodulo con: git submodule update --init w.vlink"
  exit 2
}

New-Item -ItemType Directory -Force -Path (Join-Path $vlinkDir 'objects') | Out-Null
& make -C $vlinkDir @args
exit $LASTEXITCODE
