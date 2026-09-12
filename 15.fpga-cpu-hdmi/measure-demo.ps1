<#
.SYNOPSIS
  Mide cuantos frames por segundo dibuja una demo, leyendo R21.

.DESCRIPTION
  R21 es la posicion de la banda en las cuatro demos: avanza de dos en dos y da
  la vuelta cada 112 frames dibujados. La CPU tiene que estar parada para poder
  leer un registro, asi que se para, se lee, se arranca, se deja correr un rato
  y se vuelve a parar.

  Dos cosas importan y las dos se hicieron mal la primera vez:

  - El cronometro tiene que pararse en el `halt`, NO despues de leer el
    registro. La lectura tarda unos 250 ms y contarlos como tiempo de ejecucion
    rebajaba la medida un 20 %: 60 fps reales se leian como 50.
  - La ventana tiene que ser corta. A 60 fps la banda da la vuelta en 1,9 s, y
    con ventanas mas largas el numero es ambiguo.
#>
[CmdletBinding()]
param(
    [string] $Port = 'COM3',
    [int] $Samples = 3,
    [double] $Window = 1.0
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

function Invoke-Monitor {
    & $python 'monitor.py' @args --port $Port
    if ($LASTEXITCODE -ne 0) { throw "monitor.py $($args -join ' ') fallo" }
}

function Get-Band {
    (Invoke-Monitor read-register 21) -replace '.*\((\d+)\).*', '$1'
}

$rates = @()
foreach ($i in 1..$Samples) {
    Invoke-Monitor halt | Out-Null
    $before = [int](Get-Band)
    Invoke-Monitor run | Out-Null
    $start = Get-Date

    Start-Sleep -Milliseconds ([int]($Window * 1000))

    Invoke-Monitor halt | Out-Null
    $elapsed = ((Get-Date) - $start).TotalSeconds   # se para aqui, no despues
    $after = [int](Get-Band)
    Invoke-Monitor run | Out-Null

    $advance = $after - $before
    if ($advance -lt 0) { $advance += 224 }
    $rate = ($advance / 2) / $elapsed
    $rates += $rate
    "  muestra {0}: {1,5:N1} fps  ({2,5:N1} ms/frame)" -f $i, $rate, (1000 / $rate)
}

$mean = ($rates | Measure-Object -Average).Average
"media: {0:N1} fps, {1:N1} ms por frame dibujado" -f $mean, (1000 / $mean)

# Un programa que espera al intercambio no puede pasar de los 60 Hz del video,
# asi que por encima de eso es que no espera a nadie y la cifra es CPU pura.
# Entre 57 y 63 esta enganchado, y por debajo dice cuantos frames de video
# consume cada frame dibujado.
if ($mean -gt 63) {
    "  -> por encima de los 60 Hz del video: no espera al intercambio, asi que"
    "     este es el tiempo de dibujo de la CPU sin redondear"
} elseif ($mean -ge 57) {
    "  -> enganchado a los 60 Hz del video: el dibujo cabe en un frame"
} else {
    "  -> {0:N1} frames de video por cada frame dibujado" -f (60 / $mean)
}
