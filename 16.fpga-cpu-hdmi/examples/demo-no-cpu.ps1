<#
.SYNOPSIS
  Ensena una imagen en pantalla sin ejecutar ni una instruccion en la CPU.

.DESCRIPTION
  Genera un framebuffer, lo escribe en el buffer trasero por el puerto serie y
  pide el intercambio, todo desde el PC. La CPU sigue parada: quien lee la
  SDRAM y la pinta es el subsistema de video por su cuenta.

  Por eso es el aislante de fallos mas util que hay aqui. Si la imagen aparece,
  el scanout, la SDRAM, los registros de video y la cadena DVI funcionan, y
  cualquier problema que veas con una demo esta en el programa o en la CPU.

  Son 150 KB a 1 Mbaud, asi que la carga tarda un par de segundos.

  Patrones disponibles: bars, diagonal, checker, gradient, frame.
  Repetir el ultimo comando alterna entre los dos buffers.

.EXAMPLE
  .\examples\demo-no-cpu.ps1
  .\examples\demo-no-cpu.ps1 -Pattern frame -Port COM4
#>
[CmdletBinding()]
param(
    [ValidateSet('bars', 'diagonal', 'checker', 'gradient', 'frame')]
    [string] $Pattern = 'gradient',

    [string] $Port = 'COM3'
)

$ErrorActionPreference = 'Stop'
# El script vive en examples/ pero make_framebuffer.py y monitor.py estan en la
# raiz del proyecto, que es desde donde tiene que ejecutarse.
Set-Location (Join-Path $PSScriptRoot '..')

$python = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$image = "fb_$Pattern.bin"

& $python make_framebuffer.py $Pattern $image
& $python monitor.py write-block 0x01025800 $image --port $Port
& $python monitor.py write-byte 0x80000008 1 --port $Port
