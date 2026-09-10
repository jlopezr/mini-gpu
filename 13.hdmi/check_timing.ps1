<#
.SYNOPSIS
    Build every apio env and verify the TMDS serial clock meets timing.

.DESCRIPTION
    'apio build' reports SUCCESS even when nextpnr misses the timing constraint,
    because apio passes --timing-allow-fail. It will also emit a bitstream with
    an unrouted net on nothing more than a warning. So a green build is NOT
    proof the bitstream is sound -- the fmax in hardware.pnr is the real gate.

    This script builds each [env:*] in apio.ini, reads the achieved vs required
    frequency for the 5x TMDS clock, and reports pass/fail.

    With -Fix, any failing env gets a seed sweep; the first seed that meets
    timing with the best margin is written into apio.ini as a per-env
    'nextpnr-extra-options' override.

.PARAMETER Fix
    Sweep seeds for failing envs and update apio.ini.

.PARAMETER Seeds
    Seeds to try when fixing (default 1..16).

.PARAMETER Env
    Only check these envs (default: all envs in apio.ini).

.EXAMPLE
    .\check_timing.ps1
    .\check_timing.ps1 -Fix
    .\check_timing.ps1 -Fix -Env hello -Seeds 1..40
#>
[CmdletBinding()]
param(
    [switch] $Fix,
    [int[]]  $Seeds = (1..16),
    [string[]] $Env
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$IniPath   = Join-Path $PSScriptRoot 'apio.ini'
$ClockNet  = '$glbnet$clk_pix_5x'   # the 5x TMDS serial clock

if (-not (Test-Path $IniPath)) { throw "apio.ini not found in $PSScriptRoot" }

# ---------------------------------------------------------------- helpers ---

function Get-Envs {
    # Env section names, in file order.
    (Get-Content $IniPath) |
        ForEach-Object { if ($_ -match '^\s*\[env:([^\]]+)\]\s*$') { $Matches[1] } }
}

function Get-Fmax {
    <# Returns @{Achieved; Constraint; Margin} for an env, or $null if the
       clock net is absent (e.g. a top that drives no DVI output). #>
    param([string] $EnvName)

    $pnr = Join-Path $PSScriptRoot "_build\$EnvName\hardware.pnr"
    if (-not (Test-Path $pnr)) { return $null }

    $report = Get-Content $pnr -Raw | ConvertFrom-Json
    if (-not $report.PSObject.Properties.Match('fmax').Count) { return $null }
    $entry = $report.fmax.PSObject.Properties |
                Where-Object { $_.Name -eq $ClockNet } |
                Select-Object -First 1
    if (-not $entry) { return $null }

    $a = [double] $entry.Value.achieved
    $c = [double] $entry.Value.constraint
    [pscustomobject]@{
        Achieved   = $a
        Constraint = $c
        Margin     = 100.0 * ($a - $c) / $c
        Pass       = ($a -ge $c)
    }
}

function Invoke-Build {
    <# Build one env. Returns @{Ok; Warnings; Output}. #>
    param([string] $EnvName)

    $out = (& apio build -e $EnvName 2>&1 | Out-String)
    [pscustomobject]@{
        Ok       = ($out -match 'SUCCESS')
        Warnings = ([regex]::Matches($out, 'Warning:')).Count
        Output   = $out
    }
}

function Set-EnvSeed {
    <# Write 'nextpnr-extra-options = --seed N' inside [env:NAME], replacing any
       existing line. Leaves every other section untouched. #>
    param([string] $EnvName, [int] $Seed)

    $lines  = [System.Collections.Generic.List[string]](Get-Content $IniPath)
    $start  = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*\[env:$([regex]::Escape($EnvName))\]\s*$") { $start = $i; break }
    }
    if ($start -lt 0) { throw "Section [env:$EnvName] not found in apio.ini" }

    # Extent of this section: up to the next [section] header or EOF.
    $end = $lines.Count
    for ($i = $start + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[') { $end = $i; break }
    }

    $newLine  = "nextpnr-extra-options = --seed $Seed"
    $replaced = $false
    for ($i = $start + 1; $i -lt $end; $i++) {
        if ($lines[$i] -match '^\s*nextpnr-extra-options\s*=') {
            $lines[$i] = $newLine; $replaced = $true; break
        }
    }
    if (-not $replaced) {
        # Insert after the last non-blank line of the section, so the blank
        # separator before the next section survives.
        $insert = $end
        while ($insert -gt $start + 1 -and [string]::IsNullOrWhiteSpace($lines[$insert - 1])) { $insert-- }
        $lines.Insert($insert, $newLine)
    }
    Set-Content -LiteralPath $IniPath -Value $lines
}

function Find-GoodSeed {
    <# Sweep seeds for one env; return the seed with the largest passing
       margin, or $null if none pass. #>
    param([string] $EnvName)

    $best = $null
    foreach ($s in $Seeds) {
        Set-EnvSeed -EnvName $EnvName -Seed $s
        Remove-Item -Recurse -Force (Join-Path $PSScriptRoot "_build\$EnvName") -ErrorAction SilentlyContinue
        $build = Invoke-Build -EnvName $EnvName
        if (-not $build.Ok) { Write-Host ("    seed {0,-3} build FAILED" -f $s) -ForegroundColor Red; continue }

        $f = Get-Fmax -EnvName $EnvName
        if (-not $f) { Write-Host ("    seed {0,-3} no clock net" -f $s); continue }

        $mark = if ($f.Pass) { 'ok' } else { '  ' }
        Write-Host ("    seed {0,-3} {1,7:N1} MHz {2}" -f $s, $f.Achieved, $mark)

        if ($f.Pass -and (-not $best -or $f.Achieved -gt $best.Achieved)) {
            $best = [pscustomobject]@{ Seed = $s; Achieved = $f.Achieved; Margin = $f.Margin }
        }
    }
    return $best
}

# ------------------------------------------------------------------- main ---

$envs = Get-Envs
if ($Env) {
    $unknown = $Env | Where-Object { $_ -notin $envs }
    if ($unknown) { throw "Unknown env(s): $($unknown -join ', '). Known: $($envs -join ', ')" }
    $envs = $Env
}
if (-not $envs) { throw 'No [env:*] sections found in apio.ini' }

Write-Host ''
Write-Host ("Checking {0} env(s): {1}" -f $envs.Count, ($envs -join ', ')) -ForegroundColor Cyan
Write-Host ("Required: {0} >= constraint`n" -f $ClockNet)

$results  = @()
$failed   = @()

foreach ($e in $envs) {
    Remove-Item -Recurse -Force (Join-Path $PSScriptRoot "_build\$e") -ErrorAction SilentlyContinue
    $build = Invoke-Build -EnvName $e

    if (-not $build.Ok) {
        Write-Host ("{0,-16} BUILD FAILED" -f $e) -ForegroundColor Red
        Write-Host $build.Output
        $results += [pscustomobject]@{ Env = $e; Status = 'BUILD FAILED'; Achieved = $null; Margin = $null; Warnings = $build.Warnings }
        $failed  += $e
        continue
    }

    $f = Get-Fmax -EnvName $e
    if (-not $f) {
        Write-Host ("{0,-16} built, no '{1}' in report (no DVI output?)" -f $e, $ClockNet) -ForegroundColor Yellow
        $results += [pscustomobject]@{ Env = $e; Status = 'NO CLOCK'; Achieved = $null; Margin = $null; Warnings = $build.Warnings }
        continue
    }

    $status = if ($f.Pass) { 'OK' } else { 'TIMING FAIL' }
    $colour = if ($f.Pass) { 'Green' } else { 'Red' }
    Write-Host ("{0,-16} {1,7:N1} / {2:N1} MHz   margin {3,6:N1}%   warnings {4}   {5}" -f `
                $e, $f.Achieved, $f.Constraint, $f.Margin, $build.Warnings, $status) -ForegroundColor $colour

    $results += [pscustomobject]@{ Env = $e; Status = $status; Achieved = $f.Achieved; Margin = $f.Margin; Warnings = $build.Warnings }
    if (-not $f.Pass) { $failed += $e }
}

if ($failed -and $Fix) {
    Write-Host ''
    Write-Host ("Sweeping seeds for: {0}" -f ($failed -join ', ')) -ForegroundColor Cyan
    foreach ($e in $failed) {
        Write-Host "  [$e]"
        $best = Find-GoodSeed -EnvName $e
        if ($best) {
            Set-EnvSeed -EnvName $e -Seed $best.Seed
            Remove-Item -Recurse -Force (Join-Path $PSScriptRoot "_build\$e") -ErrorAction SilentlyContinue
            Invoke-Build -EnvName $e | Out-Null
            Write-Host ("  -> seed {0} ({1:N1} MHz, margin {2:N1}%) written to apio.ini" -f `
                        $best.Seed, $best.Achieved, $best.Margin) -ForegroundColor Green
            ($results | Where-Object Env -eq $e) | ForEach-Object {
                $_.Status = 'FIXED'; $_.Achieved = $best.Achieved; $_.Margin = $best.Margin
            }
        } else {
            Write-Host ("  -> no seed in {0}..{1} met timing; widen -Seeds, or reduce the design" -f `
                        $Seeds[0], $Seeds[-1]) -ForegroundColor Red
        }
    }
} elseif ($failed) {
    Write-Host ''
    Write-Host ("{0} env(s) failed timing. Re-run with -Fix to sweep seeds." -f $failed.Count) -ForegroundColor Yellow
}

Write-Host ''
$results | Format-Table Env, Status, @{n='MHz';e={ if ($null -ne $_.Achieved) { '{0:N1}' -f $_.Achieved } }},
                        @{n='Margin';e={ if ($null -ne $_.Margin) { '{0:N1}%' -f $_.Margin } }}, Warnings -AutoSize

$stillBad = $results | Where-Object { $_.Status -in @('TIMING FAIL','BUILD FAILED') }
if ($stillBad) { exit 1 } else { exit 0 }
