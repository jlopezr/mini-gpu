# Reemplaza a una medida de una sola semilla: vuelve a emplazar y enrutar el
# netlist ya sintetizado con varias semillas y da la mediana y el rango.
#
# El fmax de una sola semilla tiene una dispersion de en torno al 15% en este
# diseno, asi que una diferencia menor que eso no demuestra nada. Ejecutar
# despues de ./check.ps1 Build, que es quien genera _build/default/hardware.json.
param([int[]]$Seeds = @(1, 2, 3, 4, 5))
$ErrorActionPreference = 'Stop'

$suite = Join-Path $env:USERPROFILE '.apio\packages\oss-cad-suite'
$env:PATH = "$suite\bin;$suite\lib;$suite\py3bin;" + $env:PATH
$netlist = Join-Path $PSScriptRoot '_build/default/hardware.json'
if (-not (Test-Path $netlist)) { throw "Falta $netlist: ejecuta ./check.ps1 Build antes" }
$work = Join-Path ([System.IO.Path]::GetTempPath()) ('sweep-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $work | Out-Null

$results = @()
foreach ($seed in $Seeds) {
    $report = Join-Path $work "seed$seed.json"
    $log = Join-Path $work "seed$seed.log"
    Push-Location $PSScriptRoot
    cmd /c "nextpnr-ecp5.exe --85k --package CABGA381 --speed 6 --seed $seed --json `"$netlist`" --report `"$report`" --lpf ulx3s_v20.lpf --timing-allow-fail --force -q > `"$log`" 2>&1"
    Pop-Location
    if (-not (Test-Path $report)) { Write-Warning "semilla $seed sin informe, ver $log"; continue }
    $json = Get-Content $report -Raw | ConvertFrom-Json
    foreach ($clock in $json.fmax.PSObject.Properties) {
        $results += [pscustomobject]@{ seed = $seed; clock = $clock.Name; fmax = $clock.Value.achieved }
    }
}

$results | Group-Object clock | ForEach-Object {
    $values = $_.Group.fmax | Sort-Object
    $median = $values[[int]([math]::Floor($values.Count / 2))]
    ''
    $_.Name
    foreach ($r in $_.Group) { '   semilla {0}: {1,7:N2} MHz' -f $r.seed, $r.fmax }
    '   mediana {0:N2} MHz   rango {1:N2} - {2:N2} MHz   dispersion {3:P0}' -f `
        $median, $values[0], $values[-1], (($values[-1] - $values[0]) / $values[0])
}
Remove-Item $work -Recurse -Force
