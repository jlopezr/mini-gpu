<#
.SYNOPSIS
  Captura N frames consecutivos de la placa, de forma determinista.

.DESCRIPTION
  Ensambla el programa, lo carga y lo deja correr hasta un intercambio CONCRETO
  usando el registro HALT_AT. Entonces la CPU esta parada, el frame acaba de
  completarse y esta entero en el buffer frontal: se lee y se guarda.

  Por que se para en el intercambio y no tras N frames de video
  ------------------------------------------------------------

  Parar cuando el contador de frames llega a N para la CPU en un punto
  cualquiera de su dibujo. El buffer trasero queda a medias, y lo que se capture
  depende de la velocidad relativa entre la CPU y el barrido -- que es justo lo
  que hace que tear_demo_fast tenga una costura viajando cada 63 ms. La captura
  saldria distinta cada vez y el test seria intermitente.

  Parando en el N-esimo intercambio COMPLETADO, el frame esta entero por
  construccion. Determinista y repetible.

  Cada frame necesita una ejecucion desde el principio, porque la unica forma de
  leer memoria es con la CPU parada. Son ~1,5 s de lectura por frame a 1 Mbaud,
  pero los programas son deterministas desde el reset, asi que el frame N sale
  igual siempre.

  Los ficheros salen como <prefijo>_NNN.bin, en RGB565 crudo de 320x240, que es
  lo que comen make_framebuffer.py y ../tools/compare-frames.py.

.EXAMPLE
  .\capture-frames.ps1 swap_demo_fast -Frames 4

.EXAMPLE
  .\capture-frames.ps1 swap_demo_fast -Frames 1 -Desde 10 -Prefijo tarde
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Program,

    # Cuantos frames consecutivos capturar.
    [int] $Frames = 3,

    # Numero del primer intercambio a capturar. Los primeros frames de las demos
    # son de arranque --los dos buffers empiezan con basura-- asi que a veces
    # interesa empezar mas tarde.
    [int] $Desde = 3,

    [string] $Prefijo = "capture",
    [string] $Port = "COM3"
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = '..\.venv\Scripts\python.exe'
$source = if ($Program.EndsWith('.asm')) { "examples\$Program" }
          else { "examples\$Program.asm" }
$binary = [System.IO.Path]::ChangeExtension($source, '.bin')

# Registros de video. La ventana es de 32 bytes desde el hito de rafagas.
$FB_FRONT   = '0x80000000'
$STATUS     = '0x8000000c'
$SWAP_COUNT = '0x80000010'
$HALT_AT    = '0x80000014'

function Invoke-Monitor {
    $salida = & $python 'monitor.py' @args --port $Port
    if ($LASTEXITCODE -ne 0) { throw "monitor.py $($args -join ' ') fallo" }
    return $salida
}

# El monitor accede byte a byte, asi que una palabra son cuatro comandos.
function Write-Reg([string] $address, [uint32] $value) {
    $base = [Convert]::ToUInt32($address, 16)
    for ($i = 0; $i -lt 4; $i++) {
        $byte = ($value -shr ($i * 8)) -band 0xFF
        Invoke-Monitor 'write-byte' ('0x{0:x8}' -f ($base + $i)) "$byte" | Out-Null
    }
}

function Read-Reg([string] $address) {
    $base = [Convert]::ToUInt32($address, 16)
    $value = [uint32] 0
    for ($i = 0; $i -lt 4; $i++) {
        $texto = Invoke-Monitor 'read-byte' ('0x{0:x8}' -f ($base + $i))
        $byte = [Convert]::ToUInt32(($texto | Select-Object -Last 1).Trim(), 16)
        $value = $value -bor ($byte -shl ($i * 8))
    }
    return $value
}

& $python '..\1.isa\miniisa_asm.py' $source -o $binary
if ($LASTEXITCODE -ne 0) { throw "el ensamblado de $source fallo" }

Write-Host "Capturando $Frames frames de $Program, desde el intercambio $Desde"

for ($n = 0; $n -lt $Frames; $n++) {
    $swap = $Desde + $n

    # El orden importa: resetear ANTES de escribir, porque el monitor rechaza
    # cualquier acceso a memoria mientras la CPU corre.
    Invoke-Monitor 'reset' | Out-Null
    Invoke-Monitor 'write-block' '0x00000000' $binary | Out-Null

    # Borrar el underflow de la pasada anterior. Sin esto, el primer frame que
    # lo provoque contamina todos los demas y no se sabe cual fallo.
    Write-Reg $STATUS 1
    Write-Reg $HALT_AT ([uint32] $swap)

    Invoke-Monitor 'run' | Out-Null

    # Esperar a que HALT_AT pare la CPU.
    $limite = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 100
        $estado = Invoke-Monitor 'status'
        $parada = ($estado -match 'halted')
    } while (-not $parada -and (Get-Date) -lt $limite)

    if (-not $parada) {
        throw "la CPU no paro en el intercambio $swap; ¿el programa hace swaps?"
    }

    $front = Read-Reg $FB_FRONT
    $status = Read-Reg $STATUS
    $swaps = Read-Reg $SWAP_COUNT

    $fichero = '{0}_{1:d3}.bin' -f $Prefijo, $swap
    Invoke-Monitor 'read-block' ('0x{0:x8}' -f $front) '153600' $fichero | Out-Null

    $under = if ($status -band 1) { 'SI' } else { 'no' }
    Write-Host ("  intercambio {0,3}: front=0x{1:x8}  swaps={2}  underflow={3}  -> {4}" -f `
                $swap, $front, $swaps, $under, $fichero)

    if ($status -band 1) {
        # ${swap} y no $swap: los dos puntos que siguen los tomaria PowerShell
        # como el separador de ambito de una variable ("$global:x") y el script
        # entero deja de compilar, asi que este script NUNCA ha llegado a
        # ejecutarse desde que se anadio esta linea.
        Write-Warning "underflow en el frame ${swap}: la imagen capturada puede estar rota"
    }
}

Write-Host ""
Write-Host "Comparar dos capturas:"
Write-Host "  ..\.venv\Scripts\python.exe ..\tools\compare-frames.py --rgb565 320x240 \"
Write-Host "      ${Prefijo}_$('{0:d3}' -f $Desde).bin ${Prefijo}_$('{0:d3}' -f ($Desde+1)).bin"
