<#
.SYNOPSIS
  Ensambla un programa, para la CPU, lo carga en la placa y lo ejecuta.

.DESCRIPTION
  Los cuatro pasos del ciclo de prueba en un solo comando. El orden importa:
  el monitor rechaza cualquier acceso a memoria mientras la CPU esta en
  marcha, asi que hay que resetearla ANTES de escribir el programa. Olvidarlo
  da un error de acceso que parece un fallo de la placa y no lo es.

  Al terminar consulta el estado de la CPU y el registro STATUS de video, y
  avisa si la CPU se ha detenido con error o si hay underflow. El bit de
  underflow es pegajoso y solo lo borra un reset de la PLACA, no
  `monitor.py reset`, asi que un aviso puede venir de una prueba anterior.

.EXAMPLE
  .\run-demo.ps1 swap_demo_fast

.EXAMPLE
  .\run-demo.ps1 tear_demo_fast -Port COM4

.EXAMPLE
  .\run-demo.ps1 swap_demo -NoRun    # cargar sin arrancar, para inspeccionar
#>
[CmdletBinding()]
param(
    # Nombre del programa, con o sin extension: swap_demo_fast, tear_demo.asm...
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Program,

    # Puerto serie de la ULX3S.
    [string] $Port = 'COM3',

    # Cargar el programa pero dejar la CPU parada.
    [switch] $NoRun
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$name = [System.IO.Path]::GetFileNameWithoutExtension($Program)
$source = "examples\$name.asm"
$binary = "examples\$name.bin"

if (-not (Test-Path $source)) {
    $disponibles = (Get-ChildItem examples\*.asm | ForEach-Object BaseName) -join ', '
    throw "No existe $source. Programas disponibles: $disponibles"
}

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

function Invoke-Monitor {
    & $python 'monitor.py' @args --port $Port
    if ($LASTEXITCODE -ne 0) { throw "monitor.py $($args -join ' ') fallo" }
}

Write-Host "== ensamblando $source" -ForegroundColor Cyan
& $python '..\1.isa\miniisa_asm.py' $source -o $binary
if ($LASTEXITCODE -ne 0) { throw "el ensamblador fallo" }

# Reset antes de escribir: con la CPU corriendo, el monitor rechaza la memoria.
Write-Host "== parando la CPU" -ForegroundColor Cyan
Invoke-Monitor reset

$bytes = (Get-Item $binary).Length
Write-Host "== cargando $binary ($bytes bytes) en 0x00000000" -ForegroundColor Cyan
Invoke-Monitor write-block 0 $binary

if ($NoRun) {
    Write-Host "== cargado; la CPU sigue parada (-NoRun)" -ForegroundColor Yellow
    return
}

Write-Host "== arrancando" -ForegroundColor Cyan
Invoke-Monitor run

# Margen para que un programa que se cae lo haga antes de mirar el estado.
Start-Sleep -Milliseconds 300

$estado = Invoke-Monitor status
Write-Host $estado
if ($estado -match 'error=True') {
    Write-Host "!! la CPU se ha detenido con error" -ForegroundColor Red
}

# STATUS de video: bit 0 underflow, bit 1 intercambio pendiente.
$video = Invoke-Monitor read-byte 0x8000000c
if ($video -match ':\s*0x([0-9a-fA-F]+)' -and ([Convert]::ToInt32($Matches[1], 16) -band 1)) {
    Write-Host "!! underflow de video marcado (pegajoso: puede venir de antes)" -ForegroundColor Red
}
