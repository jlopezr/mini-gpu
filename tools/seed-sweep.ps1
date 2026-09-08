<#
.SYNOPSIS
  Sweeps nextpnr placement seeds for an apio ECP5 project and reports the
  achieved Fmax of each one.

.DESCRIPTION
  apio never passes --seed to nextpnr, so every build uses the same built-in
  constant and produces the same routing. Different seeds explore different
  placements, which on a timing-limited design can be worth tens of MHz.

  The sweep runs nextpnr directly on the netlist apio already synthesised
  (_build/<env>/hardware.json), so synthesis runs once instead of once per
  seed. Each seed writes its own report into _build/<env>/seed-sweep/.

.EXAMPLE
  .\tools\seed-sweep.ps1 -ProjectDir 6.fpga-cpu -Seeds 1..20

.EXAMPLE
  .\tools\seed-sweep.ps1 -ProjectDir 12.fpga-gpu -Seeds 1,2,3 -KeepConfigs
#>
[CmdletBinding()]
param(
    # Apio project directory (the one holding apio.ini).
    [Parameter(Mandatory = $true)]
    [string] $ProjectDir,

    # Seeds to try.
    [int[]] $Seeds = 1..10,

    # Apio env name inside apio.ini.
    [string] $EnvName = 'default',

    # Keep each seed's .config bitstream text. Off by default: they are ~17 MB
    # each and only the winning seed is worth rebuilding properly with apio.
    [switch] $KeepConfigs
)

$ErrorActionPreference = 'Stop'

# -- Locate the oss-cad-suite binaries. nextpnr needs its own bin directory on
# -- PATH to resolve the DLLs shipped next to it; calling it by absolute path
# -- alone fails with a loader error.
$suiteRoot = Join-Path $env:USERPROFILE '.apio\packages\oss-cad-suite'
$suiteBin = Join-Path $suiteRoot 'bin'
$suiteLib = Join-Path $suiteRoot 'lib'
$nextpnr = Join-Path $suiteBin 'nextpnr-ecp5.exe'
if (-not (Test-Path $nextpnr)) {
    throw "nextpnr-ecp5 not found at $nextpnr. Is the apio oss-cad-suite package installed?"
}
# -- Both directories are required: the loader finds nextpnr's DLLs across bin
# -- and lib, and omitting lib fails with STATUS_DLL_NOT_FOUND (0xC0000135).
$env:PATH = "$suiteBin;$suiteLib;$env:PATH"

$projectPath = (Resolve-Path $ProjectDir).Path
$buildDir = Join-Path $projectPath "_build\$EnvName"
$netlist = Join-Path $buildDir 'hardware.json'

# -- The sweep reuses apio's netlist, so make sure a build exists first.
if (-not (Test-Path $netlist)) {
    Write-Host "No netlist yet, running 'apio build' once to produce it..." -ForegroundColor Yellow
    Push-Location $projectPath
    try { apio build -e $EnvName | Out-Host } finally { Pop-Location }
    if (-not (Test-Path $netlist)) { throw "apio build did not produce $netlist" }
}

# -- Read the FPGA part from the parameters apio recorded for this build, so the
# -- sweep always matches the board configured in apio.ini.
$paramsFile = Join-Path $buildDir 'scons.params'
if (-not (Test-Path $paramsFile)) { throw "Missing $paramsFile. Run 'apio build' first." }
$params = Get-Content $paramsFile -Raw

function Read-Param([string] $Name) {
    $m = [regex]::Match($params, "$Name`:\s*`"([^`"]+)`"")
    if (-not $m.Success) { throw "Could not read '$Name' from scons.params" }
    return $m.Groups[1].Value
}

# -- ecp5_params holds type/package/speed; 'type' also appears in fpga_info, so
# -- match the nested block to avoid picking up the wrong one.
$ecp5 = [regex]::Match($params, 'ecp5_params\s*\{(?<body>[^}]*)\}').Groups['body'].Value
if (-not $ecp5) { throw "This project is not an ECP5 design (no ecp5_params in scons.params)." }
$fpgaType = [regex]::Match($ecp5, 'type:\s*"([^"]+)"').Groups[1].Value
$fpgaPackage = [regex]::Match($ecp5, 'package:\s*"([^"]+)"').Groups[1].Value
$fpgaSpeed = [regex]::Match($ecp5, 'speed:\s*"([^"]+)"').Groups[1].Value

$lpf = Get-ChildItem $projectPath -Filter '*.lpf' | Select-Object -First 1
if (-not $lpf) { throw "No .lpf constraint file found in $projectPath" }

$sweepDir = Join-Path $buildDir 'seed-sweep'
New-Item -ItemType Directory -Force -Path $sweepDir | Out-Null

Write-Host ""
Write-Host "Project : $projectPath"
Write-Host "Device  : $fpgaType $fpgaPackage speed $fpgaSpeed"
Write-Host "Netlist : $netlist"
Write-Host "Seeds   : $($Seeds -join ', ')"
Write-Host ""

$results = foreach ($seed in $Seeds) {
    $report = Join-Path $sweepDir "seed-$seed.pnr"
    $config = Join-Path $sweepDir "seed-$seed.config"
    $log = Join-Path $sweepDir "seed-$seed.log"

    Write-Host ("seed {0,-4} " -f $seed) -NoNewline

    $started = Get-Date
    # -- Mirror the command apio builds in plugin_ecp5.py, plus --seed. Note
    # -- apio always passes --timing-allow-fail, so a failing seed still writes
    # -- a report; that is exactly what we want to measure.
    $arguments = @(
        "--$fpgaType"
        '--package', $fpgaPackage
        '--speed', $fpgaSpeed
        '--json', $netlist
        '--textcfg', $config
        '--report', $report
        '--lpf', $lpf.FullName
        '--timing-allow-fail'
        '--force'
        '--seed', $seed
    )
    & $nextpnr @arguments *> $log
    $elapsed = (Get-Date) - $started

    if (-not (Test-Path $report)) {
        Write-Host "ERROR (see $log)" -ForegroundColor Red
        continue
    }

    $pnr = Get-Content $report -Raw | ConvertFrom-Json
    # -- fmax is keyed by clock net name; a design may have more than one, so
    # -- report the worst offender (largest shortfall against its constraint).
    $clocks = $pnr.fmax.PSObject.Properties
    if (-not $clocks) {
        Write-Host "no clocks in report" -ForegroundColor Yellow
        continue
    }

    $worst = $clocks | Sort-Object { $_.Value.achieved - $_.Value.constraint } | Select-Object -First 1
    $achieved = [double] $worst.Value.achieved
    $constraint = [double] $worst.Value.constraint
    $slackPct = 100.0 * ($achieved - $constraint) / $constraint
    $passed = $achieved -ge $constraint

    if (-not $KeepConfigs) { Remove-Item $config -ErrorAction SilentlyContinue }

    $status = if ($passed) { 'PASS' } else { 'FAIL' }
    $color = if ($passed) { 'Green' } else { 'Red' }
    $marginText = '{0}{1:N1}%' -f $(if ($slackPct -ge 0) { '+' } else { '' }), $slackPct
    Write-Host ("{0}  {1,7:N2} / {2,7:N2} MHz  {3,8}  {4,5:N1}s" -f `
            $status, $achieved, $constraint, $marginText, $elapsed.TotalSeconds) -ForegroundColor $color

    [pscustomobject]@{
        Seed       = $seed
        Clock      = $worst.Name
        AchievedMHz = [math]::Round($achieved, 2)
        TargetMHz  = [math]::Round($constraint, 2)
        MarginPct  = [math]::Round($slackPct, 1)
        Status     = $status
        Seconds    = [math]::Round($elapsed.TotalSeconds, 1)
    }
}

if (-not $results) { throw "No seed produced a usable report." }

Write-Host ""
$results | Sort-Object AchievedMHz -Descending | Format-Table -AutoSize

$csv = Join-Path $sweepDir 'summary.csv'
$results | Sort-Object AchievedMHz -Descending | Export-Csv $csv -NoTypeInformation -Encoding utf8

$best = $results | Sort-Object AchievedMHz -Descending | Select-Object -First 1
$passing = @($results | Where-Object Status -eq 'PASS')

Write-Host "Summary written to $csv"
Write-Host ""
if ($passing.Count -gt 0) {
    Write-Host "$($passing.Count) of $($results.Count) seeds close timing. Best: seed $($best.Seed) at $($best.AchievedMHz) MHz." -ForegroundColor Green
    Write-Host "Pin it by adding this line under [env:$EnvName] in apio.ini:"
    Write-Host ""
    Write-Host "    nextpnr-extra-options = --seed $($best.Seed)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Then run 'apio build' so apio regenerates the bitstream with that seed."
} else {
    Write-Host "No seed closes timing. Best was seed $($best.Seed) at $($best.AchievedMHz) MHz vs $($best.TargetMHz) MHz target." -ForegroundColor Yellow
    Write-Host "Lower the clock or restructure the critical path; placement alone will not get you there."
}
