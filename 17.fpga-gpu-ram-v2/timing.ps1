# Resume el informe de temporización de la última síntesis: fmax por reloj y los
# nets con nombre del camino crítico. Se usa tras cada paso de optimización para
# comparar medidas equivalentes. Ejecutar después de ./check.ps1 Build.
$ErrorActionPreference = 'Stop'
$report = Get-Content (Join-Path $PSScriptRoot '_build/default/hardware.pnr') -Raw | ConvertFrom-Json

foreach ($clock in $report.fmax.PSObject.Properties) {
    '{0,8:N2} MHz  (objetivo {1} MHz)  {2}' -f $clock.Value.achieved, $clock.Value.constraint, $clock.Name
}

$paths = @($report.critical_paths)
for ($i = 0; $i -lt $paths.Count; $i++) {
    $total = ($paths[$i].path | Measure-Object -Property delay -Sum).Sum
    if ($total -lt 1) { continue }
    ''
    'camino {0}: {1:N2} ns, {2} segmentos' -f $i, $total, $paths[$i].path.Count
    $paths[$i].path |
        Where-Object { $_.net -and $_.net -notlike '*aiger*' -and $_.net -notlike '$auto*' -and $_.net -notlike '$techmap*' } |
        ForEach-Object { '   {0,6:N2} ns  {1}' -f $_.delay, $_.net }
}

# Recuento de recursos comparable entre iteraciones.
''
foreach ($name in 'TRELLIS_COMB', 'TRELLIS_FF', 'DP16KD') {
    $cell = $report.utilization.$name
    if ($cell) { '{0,-14} {1} / {2}' -f $name, $cell.used, $cell.available }
}
